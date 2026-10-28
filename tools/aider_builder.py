#!/usr/bin/env python3
"""The Aider builder, track A (SEB-301). Once a day, one job, on GitHub Actions.

    python3 tools/aider_builder.py             # the top job with `track: aider`, if the builder has not run today
    python3 tools/aider_builder.py --force     # run even if it ran today (the Run workflow button)
    python3 tools/aider_builder.py --job 1a    # that job, not the top one
    python3 tools/aider_builder.py --self-test

Aider (architect mode) through OpenRouter: Sonnet plans, qwen3-coder writes the edits. The test command is tools/aider_checks.py,
the offline commands of checks.yml. A job is capped at 30 model turns (counted in Aider's own LLM log; the process is killed on
the 31st) and at 25 minutes. The cost of a job is OpenRouter's own figure: the key's `usage` before and after the run, never
Aider's estimate. It goes to data/agent_spend.csv as `SEB-301/aider/<job>`, so the $20 month cap in tools/llm.py counts it.

The PR, the tick, the `built:` line for a collection job and the line on SEB-301 reuse tools/one_call.py. A job that fails twice
(two `failed` rows in data/aider_log.csv) is blocked in BACKLOG.md with `needs-claude:` and the builder takes the next one; the
weekly Claude Code task takes at most 2 of those (docs/aider_track.md). During the pilot only jobs that carry a `track: aider`
line are taken here, and the one-call builder skips them (tools/backlog.py next_job).

Env: OPENROUTER_API_KEY, LINEAR_API_KEY, GH_PUSH_TOKEN, GITHUB_REPOSITORY. Model ids are set in this file and nowhere else.
"""
import csv
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import backlog  # noqa: E402
import job_shape  # noqa: E402
import llm  # noqa: E402
import one_call  # noqa: E402

LOG = os.path.join(ROOT, "data", "aider_log.csv")
LOG_HEADER = ["ts_utc", "status", "job", "pr", "cost_usd", "turns", "detail"]
TRACK = "aider"
ARCHITECT_FALLBACK = "anthropic/claude-sonnet-5.5"
EDITOR = "qwen/qwen3-coder"
MAX_TURNS = 30
JOB_CAP_USD = 2.00            # a runaway job is killed here; the month cap in llm.py is the real ceiling
MAX_MINUTES = 25
FAILS_BEFORE_CLAUDE = 2
KEY_URL = llm.API + "/key"
TASK_RULES = """Rules for this change:
- Change only the files you were given. Do not create other files.
- Real data only. Never type a number that comes from a data file. A new data CSV is created with its header line only, never a row.
- Copy values from existing entries exactly where the job says to copy them. Do not invent a fee.
- No em-dashes anywhere. Short sentences, plain words.
- The test command runs the repo's offline checks. Make them pass. Do not edit a check to make it pass.
"""


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def sh(cmd, check=True, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError("%s failed: %s" % (" ".join(cmd), (r.stdout + r.stderr)[-500:]))
    return r


# ---------- the log ----------

def log_rows(path=LOG):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def ran_today(rows, day=None):
    day = day or now().date().isoformat()
    return any(r["ts_utc"][:10] == day for r in rows)


MAX_JOBS_PER_DAY = 3          # one per daily slot (25 Oct, Seb: the queue must move); the month cap in llm.py still holds


def jobs_today(rows, day=None):
    """Build attempts today. A 'nothing' row (empty queue, month cap) is not an attempt."""
    day = day or now().date().isoformat()
    return sum(1 for r in rows if r["ts_utc"][:10] == day and r["status"] not in ("nothing",))


def failures(rows, job):
    return sum(1 for r in rows if r["job"] == job and r["status"] == "failed")


# ---------- OpenRouter's own figures ----------

def key_usage(key, opener=None):
    """Total credits the key has used, as OpenRouter reports it (dollars)."""
    req = urllib.request.Request(KEY_URL, headers={"Authorization": "Bearer " + key})
    with (opener or urllib.request.urlopen)(req, timeout=30) as r:
        return float(json.loads(r.read())["data"]["usage"])


def settled_usage(key, floor, reader=key_usage, tries=4, wait=5):
    """The usage figure can trail the last call by a few seconds: read until two reads in a row agree."""
    prev = None
    for _ in range(tries):
        cur = reader(key)
        if prev is not None and cur == prev:
            return cur
        prev = cur
        time.sleep(wait)
    return max(prev, floor)


def count_turns(history_text):
    """Model requests in Aider's LLM history file: one `TO LLM` header per request."""
    return len(re.findall(r"^TO LLM ", history_text, re.M))


# ---------- the work ----------

def task_message(i):
    return i["description"] + "\n\n" + TASK_RULES


DERIVED = ["data/routes_hourly.json", "data/routes_breakdown.json"]    # written by tools/emit_routes.py; a new route makes them stale (the pilot's third run)
PARTS = "parts"              # inside the scratch repo Aider works in (see make_parts)


def make_parts(job, tmp):
    """Aider works in a scratch git repo that holds only what the job needs: the job's files (a file too big to send whole, named
    by the job's `excerpt:` lines, as part files, as in tools/one_call.py) and its read-only context. Aider adds any file the
    model names to the chat, and in the real repo that pulled in data/samples.csv (5.8 million tokens); in the scratch repo there is
    nothing else to add. The first run, on whole files, cost $2.57 in 5 turns. Returns (scratch dir, files for Aider, manifest
    path, note for the task)."""
    work = os.path.join(tmp, "work")
    os.makedirs(os.path.join(work, PARTS), exist_ok=True)
    by_file = {}
    for e in job["excerpts"]:
        if len(e) == 3:
            by_file.setdefault(e[0], []).append((e[1], e[2]))
    files, regions, whole, notes = [], {}, [], []
    for p in job["files"]:
        full = os.path.join(ROOT, p)
        text = open(full).read() if os.path.exists(full) else ""
        if p not in by_file:
            os.makedirs(os.path.dirname(os.path.join(work, p)) or work, exist_ok=True)
            open(os.path.join(work, p), "w").write(text)
            files.append(p)
            whole.append(p)
            continue
        regions[p] = []
        for n, (a, b) in enumerate(by_file[p], 1):
            part_text = one_call.excerpt(text, a, b)
            if part_text is None or text.count(part_text) != 1:
                raise RuntimeError("excerpt %d of %s does not match exactly once" % (n, p))
            part = "%s/%s.part%d%s" % (PARTS, os.path.splitext(os.path.basename(p))[0], n, os.path.splitext(p)[1])
            open(os.path.join(work, part), "w").write(part_text + "\n")
            regions[p].append({"orig": part_text, "part": part})
            files.append(part)
            notes.append("- %s is shown as %s, the lines from `%s` to `%s`" % (p, part, a, b))
    for p in job["context"]:
        os.makedirs(os.path.dirname(os.path.join(work, p)) or work, exist_ok=True)
        shutil.copy(os.path.join(ROOT, p), os.path.join(work, p))
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=aider", "-c", "user.email=aider@example.invalid", "commit", "-q", "-m", "start"]):
        subprocess.run(["git"] + c, cwd=work, capture_output=True, check=True)
    mf = os.path.join(tmp, "parts.json")
    json.dump({"work": work, "whole": whole, "regions": regions, "regen": backlog.is_collection(job),
               "pristine": {p: open(os.path.join(ROOT, p)).read() for p in regions}}, open(mf, "w"))
    note = ""
    if notes:
        note = ("\nSome files are too big to send whole, so you are given part files. Edit only the part files. They are put back into "
                "the real file before the tests run. Keep each part's first and last lines in place unless the job says to change them:\n"
                + "\n".join(notes) + "\n")
    return work, files, mf, note


def keep_original(orig, new):
    """Only insertions survive: a line of the table that the model deleted or rewrote is put back. Used for the .py parts of a
    collection job, where tools/check_additive.py refuses any rewritten line and the editor model kept swapping a constant's name for
    a literal in four existing entries (pilot runs 9 to 11)."""
    import difflib
    a, b = orig.split("\n"), new.split("\n")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        out += b[j1:j2] if tag in ("equal", "insert") else a[i1:i2]
    return "\n".join(out)


def splice(manifest_path):
    """Put the scratch repo's work into the real repo: whole files are copied, part files are joined back into their file from its
    pristine text. Safe to run again and again (it is the first half of Aider's test command)."""
    m = json.load(open(manifest_path))
    for p in m["whole"]:
        src = os.path.join(m["work"], p)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(ROOT, p)) or ROOT, exist_ok=True)
            shutil.copy(src, os.path.join(ROOT, p))
    for p, regions in m["regions"].items():
        text = m["pristine"][p]
        for r in regions:
            new = open(os.path.join(m["work"], r["part"])).read()
            new = new[:-1] if new.endswith("\n") and not r["orig"].endswith("\n") else new
            if m.get("regen") and r["part"].endswith(".py"):
                new = keep_original(r["orig"], new.rstrip("\n"))
            assert text.count(r["orig"]) == 1, "region lost in %s" % p
            o = r["orig"].split("\n")
            if new.split("\n")[0] != o[0] or o[-1] not in new.split("\n"):
                print("%s: a part must start with its original first line (%r) and keep its original last line. "
                      "Put new lines inside the part, never above it." % (r["part"], o[0][:60]))
                raise SystemExit(1)
            text = text.replace(r["orig"], new, 1)
        open(os.path.join(ROOT, p), "w").write(text)
    if m.get("regen"):
        r = subprocess.run([sys.executable, "tools/emit_routes.py"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print("tools/emit_routes.py failed:\n" + (r.stdout + r.stderr)[-1500:])
            raise SystemExit(1)


def aider_cmd(job, architect, msg_file, tmp, files=None, manifest=None):
    c = ["aider", "--model", "openrouter/" + architect, "--architect", "--editor-model", "openrouter/" + EDITOR,
         "--editor-edit-format", "editor-diff", "--yes-always", "--no-auto-commits", "--no-dirty-commits", "--no-gitignore",
         "--no-pretty", "--no-stream", "--no-check-update", "--no-analytics", "--no-show-model-warnings", "--no-suggest-shell-commands",
         "--no-detect-urls", "--map-tokens", "0", "--auto-test",
         "--test-cmd", "cd %s && python3 tools/aider_builder.py --splice %s && python3 tools/aider_checks.py && (python3 tools/check_additive.py --worktree || { echo 'Lines you removed or rewrote. Put every one back exactly as it was:'; git diff -U0 HEAD -- collector.py collector_providers.py .github/workflows/collect.yml | grep '^-[^-]' | cut -c1-200 | head -20; exit 1; })" % (ROOT, manifest),
         "--message-file", msg_file, "--llm-history-file", os.path.join(tmp, "llm.txt"),
         "--input-history-file", os.path.join(tmp, "input.txt"), "--chat-history-file", os.path.join(tmp, "chat.md")]
    for p in job["context"]:
        c += ["--read", p]
    for p in (files if files is not None else job["files"]):
        c += ["--file", p]
    return c


def run_aider(cmd, hist, key, start_usage, cwd=ROOT, clock=time.time, reader=key_usage):
    """Run Aider, watching its LLM log. Returns (exit code, turns, reason or '')."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    import threading
    t = threading.Thread(target=lambda: out.extend(p.stdout), daemon=True)
    t.start()
    t0, last_cost, why, turns = clock(), clock(), "", 0
    while p.poll() is None:
        time.sleep(3)
        turns = count_turns(open(hist).read()) if os.path.exists(hist) else 0
        if turns > MAX_TURNS:
            why = "turn cap: %d model turns, the limit is %d" % (turns, MAX_TURNS)
        elif clock() - t0 > MAX_MINUTES * 60:
            why = "time cap: %d minutes" % MAX_MINUTES
        elif clock() - last_cost > 10:
            last_cost = clock()
            try:
                if reader(key) - start_usage > JOB_CAP_USD:
                    why = "cost cap: over $%.2f" % JOB_CAP_USD
            except Exception:       # noqa: BLE001 - the final read below is the one that must work
                pass
        if why:
            p.kill()
            break
    p.wait()
    t.join(5)
    turns = count_turns(open(hist).read()) if os.path.exists(hist) else turns
    print("".join(out)[-3000:])
    return p.returncode, turns, why


def tidy(allowed):
    """Undo anything outside the job's files. Returns the files that changed inside them."""
    changed = [l[3:].strip().strip('"') for l in sh(["git", "status", "--porcelain"]).stdout.splitlines()]
    keep = []
    for p in changed:
        if p in allowed:
            keep.append(p)
        elif sh(["git", "ls-files", "--error-unmatch", p], check=False).returncode == 0:
            sh(["git", "checkout", "--", p])
        else:
            shutil.rmtree(os.path.join(ROOT, p), ignore_errors=True) if os.path.isdir(os.path.join(ROOT, p)) else os.remove(os.path.join(ROOT, p))
    return keep


def post(text):
    try:
        i = one_call.linear.find(one_call.BACKLOG_ISSUE)
        one_call.linear.call("""mutation($id: String!, $b: String!) {
          commentCreate(input: { issueId: $id, body: $b }) { success }
        }""", {"id": i["id"], "b": "🛠️ **Aider builder (track A):** " + text})
    except SystemExit:
        print("could not post on SEB-301", file=sys.stderr)


def already_built(job, exists=None):
    """The job's own test (tests/agent_*.py) when it is already on main, else None. A track A job's test is a new file, so if it
    exists someone built the job without ticking it (20a on 26 Oct: two wasted runs, then needs-claude)."""
    exists = exists or (lambda p: os.path.exists(os.path.join(ROOT, p)))
    for p in job["files"]:
        if job_shape.TEST.match(p) and exists(p):
            return p
    return None


def branch_for(job):
    return "aider/backlog-%s" % job["id"].lower()


def open_pr_branches(opener=None):
    """Head branches of the open PRs (GitHub REST API). A job whose branch is in this set is already built and waiting on its
    checks (22a on 27 Oct: rebuilt again and again while #711 sat open). Raises on any API error: no quiet fallback."""
    repo = os.environ.get("GITHUB_REPOSITORY", "SebR214/margin")
    token = os.environ.get("GH_PUSH_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    out, page = set(), 1
    while True:
        req = urllib.request.Request("https://api.github.com/repos/%s/pulls?state=open&per_page=100&page=%d" % (repo, page),
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
        with (opener or urllib.request.urlopen)(req, timeout=30) as r:
            prs = json.loads(r.read())
        out |= {p["head"]["ref"] for p in prs}
        if len(prs) < 100:
            return out
        page += 1


def pick(items, only=None, open_branches=()):
    """The job to build: the top ready job in BACKLOG.md, or the one asked for.

    Since 24 Oct (Seb) the Aider builder is the builder for every backlog job: any job that is not done, blocked or built, lists
    its files, and carries no track or `track: aider`. A job marked `track: claude` is left for the weekly Claude slot. The pilot
    limit to items 1 to 3 is gone: it left the builder idle from 23 Oct with ready jobs in the queue. Since 25 Oct a job that changes an
    existing collector, a page or a method is track B and skipped (tools/job_shape.py), unless asked for by --job. Since 28 Oct a job
    with an open PR on its branch aider/backlog-<id> is skipped, even by --job (`open_branches`, from open_pr_branches())."""
    for it in items:
        if it["done"]:
            continue
        for j in it["jobs"]:
            if only and j["id"] != only:
                continue
            if not j["done"] and not j["blocked"] and not j["built"] and j["files"] and j["track"] in ("", TRACK) \
                    and (only or not job_shape.forbidden(j["files"])) and branch_for(j) not in open_branches:
                return it, j
    return None


def build(force, only):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 1
    rows = log_rows()
    ts = now().isoformat()
    if not force and jobs_today(rows) >= MAX_JOBS_PER_DAY:
        print("the Aider builder already made %d attempts today (data/aider_log.csv), nothing to do" % MAX_JOBS_PER_DAY)
        return 0
    month = llm.month_spend()
    if month + JOB_CAP_USD > llm.MONTHLY_CAP_USD:
        print("refused: this month so far $%.2f plus up to $%.2f for this job is over the $%.2f cap" % (month, JOB_CAP_USD, llm.MONTHLY_CAP_USD))
        one_call.commit_main([[ts, "nothing", "", "", "0.000000", 0, "month cap"]], [], "aider builder: month cap", LOG, LOG_HEADER)
        return 0
    text = open(backlog.PATH).read()
    items = backlog.parse(text)
    try:
        open_branches = open_pr_branches()
    except Exception as e:
        print("could not list open PRs: %s" % e, file=sys.stderr)
        return 1
    nj = pick(items, only, open_branches)
    stale = []
    while nj and not only and already_built(nj[1]):
        stale.append((nj[1]["id"], already_built(nj[1])))
        nj[1]["blocked"] = "already built"
        nj = pick(items, only, open_branches)
    if stale:
        ops = [("block", jid, "already built? %s is already on main, so a session built it. Check it and tick the job" % t) for jid, t in stale]
        rows = [[ts, "skipped", jid, "", "0.000000", 0, "already built: %s exists" % t] for jid, t in stale]
        one_call.commit_main(rows, ops, "aider builder: %s already built" % ", ".join(j for j, _ in stale), LOG, LOG_HEADER)
    if not nj:
        print("no job with `track: aider` is ready")
        one_call.commit_main([[ts, "nothing", "", "", "0.000000", 0, "no job with track: aider is ready"]], [], "aider builder: nothing to build", LOG, LOG_HEADER)
        return 0
    item, job = nj
    if backlog.is_collection(job) and not job["rows"]:
        why = "a collection job needs a rows: line saying where its first rows land (item 0, rule d)"
        one_call.commit_main([[ts, "failed", job["id"], "", "0.000000", 0, why]], [("block", job["id"], why)], "aider builder: %s blocked" % job["id"], LOG, LOG_HEADER)
        return 0
    i = one_call.backlog_issue(item, job)
    i.update(branch=branch_for(job), runner="Aider builder (Sonnet architect, qwen3-coder editor)")
    architect = ARCHITECT_FALLBACK
    try:
        architect = llm.resolve_sonnet()
    except Exception as e:      # noqa: BLE001
        print("could not list OpenRouter models, using %s: %s" % (architect, e), file=sys.stderr)
    for m in (architect, EDITOR):
        assert not llm.BANNED.search(m), m
    tmp = tempfile.mkdtemp(prefix="aider-")
    msg = os.path.join(tmp, "task.txt")
    sh(["git", "checkout", "-q", "main"], check=False)
    work, files, manifest, note = make_parts(job, tmp)
    open(msg, "w").write(task_message(i) + note)
    before = key_usage(key)
    code, turns, why = run_aider(aider_cmd(job, architect, msg, tmp, files, manifest), os.path.join(tmp, "llm.txt"), key, before, cwd=work)
    after = settled_usage(key, before)
    splice(manifest)
    cost = max(0.0, after - before)
    allowed = set(job["files"]) | (set(DERIVED) if backlog.is_collection(job) else set())
    changed = tidy(allowed)
    problems = []
    if why:
        problems.append(why)
    if not changed:
        problems.append("Aider changed none of the job's files")
    else:
        for cmd in (["tools/aider_checks.py"], ["tools/check_additive.py", "--worktree"]):
            bad = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True)
            if bad.returncode != 0:
                problems.append("%s fails: %s" % (os.path.basename(cmd[0]), (bad.stdout.strip().split("\n")[1:2] or bad.stdout.strip().split("\n")[:1] or ["see log"])[0][:160]))
    spend_row = {"ts_utc": ts, "issue": "%s/%s/%s" % (one_call.BACKLOG_ISSUE, TRACK, job["id"]), "model": "openrouter/%s+%s" % (architect, EDITOR),
                 "tokens_in": "", "tokens_out": "", "cost_usd": "%.6f" % cost, "result": "ok" if not problems else "failed"}
    llm.LOGGED.append(spend_row)
    url, status, detail, ops = None, "failed", "; ".join(problems), []
    if not problems:
        try:
            url = one_call.open_pr(i, changed, [{"model": architect + " + " + EDITOR, "cost_usd": "%.6f" % cost}])
            one_call.tick_on_branch(i, url)
            status, detail = "built", job["title"]
        except Exception as e:      # noqa: BLE001
            detail = "could not open the PR: %s" % e
    pr = one_call.pr_number(url) or ""
    if status == "failed":
        n = failures(rows, job["id"]) + 1
        if n >= FAILS_BEFORE_CLAUDE:
            ops.append(("block", job["id"], "needs-claude: the Aider builder failed %d times, last: %s" % (n, detail[:160])))
    sh(["git", "checkout", "-q", "-f", "main"], check=False)
    line = ("job %s (%s): %s. Cost $%.4f (OpenRouter's figure), %d model turns%s." % (
        job["id"], job["title"][:70], ("PR #%s" % pr) if status == "built" else "failed: " + detail[:160], cost, turns,
        ", needs-claude" if ops else ""))
    post(line)
    one_call.commit_main([[ts, status, job["id"], pr, "%.6f" % cost, turns, detail[:200]]], ops, "aider builder run %s" % ts, LOG, LOG_HEADER)
    print(line)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


def self_test():
    assert count_turns("TO LLM 2026-10-22 06:00:00\nx\nLLM RESPONSE 2026\nTO LLM 2026-10-22 06:01:00\n") == 2
    assert count_turns("a line saying TO LLM in the middle\n") == 0
    rs = [{"ts_utc": "2026-10-22T06:00:00+00:00", "status": "failed", "job": "1a"}, {"ts_utc": "2026-10-21T06:00:00+00:00", "status": "failed", "job": "1a"},
          {"ts_utc": "2026-10-21T06:00:00+00:00", "status": "built", "job": "2a"}]
    assert failures(rs, "1a") == 2 and failures(rs, "2a") == 0 and ran_today(rs, "2026-10-22") and not ran_today(rs, "2026-10-23")
    assert jobs_today(rs, "2026-10-21") == 2 and jobs_today(rs + [{"ts_utc": "2026-10-21T09:00:00+00:00", "status": "nothing", "job": ""}], "2026-10-21") == 2
    reads = iter([1.0, 1.5, 1.5])
    assert settled_usage("k", 1.0, reader=lambda k: next(reads), wait=0) == 1.5, "usage is read until two reads agree"
    assert key_usage("k", opener=lambda req, timeout=0: type("R", (), {"read": lambda s: b'{"data": {"usage": 3.25}}', "__enter__": lambda s: s, "__exit__": lambda s, *a: False})()) == 3.25
    t = ("- [ ] 1. Route\n  - [ ] 1a. Add it\n    files: `a.py`\n    track: aider\n- [ ] 2. Other\n  - [ ] 2a. Plain\n    files: `b.py`\n"
         "- [ ] 9. Late\n  - [ ] 9a. Late\n    files: `c.py`\n    track: aider\n")
    items = backlog.parse(t)
    assert pick(items)[1]["id"] == "1a", "the top aider job"
    assert backlog.next_job(items)[1]["id"] == "2a", "the one-call builder skips a track: aider job"
    assert backlog.next_job(items, "aider")[1]["id"] == "1a"
    t2 = t.replace("    files: `a.py`\n    track: aider", "    files: `a.py`\n    track: aider\n    blocked: x (2026-10-22)")
    assert pick(backlog.parse(t2))[1]["id"] == "2a", "1a is blocked, so the next ready job, untagged, is the Aider builder's too"
    t3 = t2.replace("    files: `b.py`\n", "    files: `b.py`\n    track: claude\n")
    assert pick(backlog.parse(t3))[1]["id"] == "9a", "a track: claude job is left for the Monday Claude task, and no pilot limit"
    assert pick(backlog.parse(t2), "9a")[1]["id"] == "9a", "--job picks the job asked for"
    t4 = t.replace("    files: `a.py`\n", "    files: `collector.py` `a.py`\n")
    assert pick(backlog.parse(t4))[1]["id"] == "2a", "a job that changes collector.py is track B, the builder skips it"
    assert pick(items, None, {"aider/backlog-1a"})[1]["id"] == "2a", "1a has an open PR, so the next job"
    assert pick(items, None, {"aider/backlog-9a"})[1]["id"] == "1a" and pick(items, None, {"aider/backlog-1a", "aider/backlog-2a"})[1]["id"] == "9a"
    assert pick(items, "1a", {"aider/backlog-1a"}) is None, "--job does not rebuild a job with an open PR either"
    page = json.dumps([{"head": {"ref": "aider/backlog-22a"}}, {"head": {"ref": "main-fix"}}]).encode()
    fake = lambda req, timeout=0: type("R", (), {"read": lambda s: page, "__enter__": lambda s: s, "__exit__": lambda s, *a: False})()
    assert open_pr_branches(fake) == {"aider/backlog-22a", "main-fix"}
    j = {"files": ["tools/x.py", "tests/agent_x.py"]}
    assert already_built(j, {"tests/agent_x.py"}.__contains__) == "tests/agent_x.py"
    assert already_built(j, set().__contains__) is None
    assert already_built({"files": [".github/workflows/watchdog.yml"]}, lambda p: True) is None, "a chat job without an agent test is never skipped"
    for m in (ARCHITECT_FALLBACK, EDITOR):
        assert not llm.BANNED.search(m), "no model of the two larger families"
    c = aider_cmd({"files": ["a.py"], "context": ["m.md"]}, "anthropic/claude-sonnet-5.5", "/t/task", "/t", None, "/t/parts.json")
    assert "--architect" in c and "--splice /t/parts.json" in c[c.index("--test-cmd") + 1]
    assert c[c.index("--model") + 1] == "openrouter/anthropic/claude-sonnet-5.5" and c[c.index("--editor-model") + 1] == "openrouter/qwen/qwen3-coder"
    assert c[c.index("--test-cmd") + 1].startswith("cd ") and "check_additive.py --worktree" in c[c.index("--test-cmd") + 1]
    assert "--no-auto-commits" in c and c.count("--file") == 1 and c.count("--read") == 1
    assert "\u2014" not in TASK_RULES
    with tempfile.TemporaryDirectory() as d:
        global ROOT
        old = ROOT
        ROOT = os.path.join(d, "repo")
        os.makedirs(ROOT)
        try:
            src = "a = 1\nTABLE = {\n  'x': 1,\n}\nb = 2\nLIST = [\n  1,\n]\nc = 3\n"
            open(os.path.join(ROOT, "big.py"), "w").write(src)
            open(os.path.join(ROOT, "small.py"), "w").write("s = 1\n")
            open(os.path.join(ROOT, "big_data.csv"), "w").write("never copied\n")
            job = {"files": ["big.py", "small.py"], "context": [], "excerpts": [["big.py", r"^TABLE = \{", r"^\}"], ["big.py", r"^LIST = \[", r"^\]"]]}
            work, files, mf, note = make_parts(job, d)
            assert files == ["parts/big.part1.py", "parts/big.part2.py", "small.py"] and "Edit only the part files" in note, files
            assert sorted(os.listdir(work)) == [".git", "parts", "small.py"], "the scratch repo holds only the job's files"
            splice(mf)
            assert open(os.path.join(ROOT, "big.py")).read() == src, "untouched parts splice back to the same file"
            open(os.path.join(work, files[0]), "w").write("NEW = 1\nTABLE = {\n  'x': 1,\n}\n")
            try:
                splice(mf)
                raise AssertionError("a line above a part must be refused")
            except SystemExit:
                pass
            open(os.path.join(work, files[0]), "w").write("TABLE = {\n  'x': 1,\n  'y': 2,\n}\n")
            open(os.path.join(work, "small.py"), "w").write("s = 2\n")
            splice(mf)
            splice(mf)
            assert open(os.path.join(ROOT, "big.py")).read() == src.replace("  'x': 1,\n", "  'x': 1,\n  'y': 2,\n"), "a part edit lands once, and splicing twice is the same"
            assert open(os.path.join(ROOT, "small.py")).read() == "s = 2\n", "a whole file is copied back"
        finally:
            ROOT = old
    print("aider_builder self-test: ok")


def main(argv):
    if "--self-test" in argv:
        self_test()
        return 0
    if "--splice" in argv:
        splice(argv[argv.index("--splice") + 1])
        return 0
    only = argv[argv.index("--job") + 1] if "--job" in argv else None
    return build("--force" in argv or only is not None, only)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
