#!/usr/bin/env python3
"""One-call runner (SEB-274). One cheap model call per job, not an agent loop.

    python3 tools/one_call.py            # take the next ready issue, if any
    python3 tools/one_call.py SEB-273    # run one issue by hand

Once a day (Seb, 20 Oct) the runner builds the top unchecked job of BACKLOG.md (tools/backlog.py): it first copies any new
"Queued by Claude" items from SEB-301 comments into the file, takes the next job that has files, builds it, opens a PR titled
`SEB-301: {job}` (automerge merges it on green), ticks the job in the same PR with the PR number and date, writes a row to
data/builder_log.csv and posts one line on SEB-301. A job that fails twice is marked `blocked:` in BACKLOG.md and the runner takes the next
one (up to 3 tries a run); it stops after the first PR. A job that changes a published number lists METHODOLOGY.md in its files and
bumps INDEX_VERSION in the same PR. Run `python3 tools/one_call.py --backlog` for that mode by hand.

The older flow still works: a ready issue is in Todo, carries the label `one-call`, and does not carry
`needs-claude`. Its description lists the files the model may change under a
`## Files` heading, and optional read-only files under `## Context`, one
backticked path per line. Linear documents attached to the issue (the
reference page) are sent too. Nothing else is loaded.

Flow: one call to qwen (kimi if qwen errors). The returned files are written,
then the offline checks run. Pass: open a PR and comment on the issue. Fail:
one retry with the check output, unless the retry prompt is over the size
limit (then no retry). Fail, or break: label `needs-claude` and stop. The
issue is never put back in Todo, so the runner cannot pick it up again.

Caps: 2 calls and $1 per job, DAILY_CAP_USD (default $3) per UTC day, and the
$20 month for all agents together, enforced by tools/llm.py, which also makes
the call and logs it to data/agent_spend.csv with the cost OpenRouter reports.

Exit codes: 0 for a clean pass, including "nothing to do" and "daily cap
reached". 1 when something is broken that a person must see (no credit, no
key, Linear unreachable). A non-zero exit fails the workflow run, and GitHub
emails the failure.

Env: OPENROUTER_API_KEY, LINEAR_API_KEY, GH_PUSH_TOKEN (to open PRs that run
CI), GITHUB_REPOSITORY.
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents"))
import linear  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools"))
import llm  # noqa: E402
import backlog  # noqa: E402

BUILDER_LOG = os.path.join(ROOT, "data", "builder_log.csv")
BUILDER_LOG_HEADER = ["ts_utc", "status", "job", "pr", "detail"]
BACKLOG_ISSUE = "SEB-301"
MAX_JOBS_PER_RUN = 3
LABEL = "one-call"
STUCK_LABEL = "needs-claude"
MODELS = ["qwen/qwen3-coder", "moonshotai/kimi-k2"]
MAX_CALLS = 2
JOB_CAP_USD = 1.00
DAILY_CAP_USD = float(os.environ.get("DAILY_CAP_USD", "3.00"))
MAX_TOKENS = 32000
BIG_FILE = 40_000          # a listed file over this many characters is sent in parts (the job's excerpt: lines) and changed by EDIT blocks
CHECKS = [
    ["python3", "tools/check_inventory.py"],
    ["python3", "tools/check_copy.py"],
    ["python3", "tools/check_design.py"],
]

SYSTEM = """You change files in a small static website repo.
You get one task, the files you may change, read-only context files, and
sometimes a reference page to match.
Rules:
- Change only the files listed under FILES YOU MAY CHANGE.
- Keep every reader-facing word as it is unless the task says otherwise.
- Never type a number into a page. Numbers come from the data files the
  code already reads.
- Return each changed file in full, exactly in this form, and nothing else:
<<<FILE path/to/file>>>
full file contents
<<<END>>>
- A file shown IN PARTS is too big to return. Change it only with edits:
<<<EDIT path/to/file>>>
<<<FIND>>>
lines copied exactly from the part shown, enough that they occur once in the file
<<<REPLACE>>>
the lines that take their place
<<<END>>>
  To add lines, FIND the line they go after and REPLACE it with that same line followed by the new ones.
No code fences, no other tags, nothing before or after the blocks.
"""


class Broken(Exception):
    """Something a person must see. Fails the run."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def sh(cmd, check=True, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise Broken("%s failed: %s" % (" ".join(cmd), (r.stderr or r.stdout)[-800:]))
    return r


# ---------- spend log (the rows themselves are written by tools/llm.py) ----------

def spent_today():
    return llm.spent_today()


def commit_spend():
    """Put this run's rows on main and push. The runner may be on a PR branch,
    so: drop the working-tree copy of the file, go to origin/main, write the
    rows again, commit, push. Retries a rebase, like collect.yml."""
    rows = list(llm.LOGGED)
    if not rows or os.environ.get("ONE_CALL_DRY_RUN"):
        return
    for attempt in range(3):
        sh(["git", "fetch", "-q", "origin", "main"])
        sh(["git", "checkout", "-q", "--", "data/agent_spend.csv"], check=False)
        sh(["git", "checkout", "-q", "-B", "main", "origin/main"])
        llm.write_rows(rows)
        sh(["git", "add", "data/agent_spend.csv"])
        sh(["git", "commit", "-q", "-m", "one-call spend %s" % now().isoformat()])
        if sh(["git", "push", "-q", "origin", "main"], check=False).returncode == 0:
            return
    raise Broken("could not push data/agent_spend.csv after 3 tries")


# ---------- Linear ----------

def issue_with_docs(ident):
    i = linear.find(ident)
    d = linear.call("""query($id: String!) {
      issue(id: $id) { documents { nodes { title content } } }
    }""", {"id": i["id"]})
    i["docs"] = d["issue"]["documents"]["nodes"]
    return i


def labels(i):
    return {l["name"].lower() for l in i["labels"]["nodes"]}


def next_ready():
    ready = [i for i in linear.issues_in_project()
             if i["state"]["type"] == "unstarted"
             and LABEL in labels(i) and STUCK_LABEL not in labels(i)]
    ready.sort(key=lambda x: (x["priority"] or 99, x["sortOrder"]))
    return ready[0]["identifier"] if ready else None


def comment(i, text):
    if i.get("backlog"):
        print("[%s] %s" % (i["identifier"], text.replace("\n", " ")[:300]))
        return
    linear.call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": "⚙️ **One-call runner**\n\n" + text})


def set_state(i, name):
    if i.get("backlog"):
        return
    st = linear.states()
    if name in st:
        linear.call("""mutation($id: String!, $s: String!) {
          issueUpdate(id: $id, input: { stateId: $s }) { success }
        }""", {"id": i["id"], "s": st[name]["id"]})


def add_label(i, name):
    if i.get("backlog"):
        return
    linear.call("""mutation($id: String!, $l: String!) {
      issueAddLabel(id: $id, labelId: $l) { success }
    }""", {"id": i["id"], "l": linear._label_id(name)})


# ---------- the job ----------

def paths_under(desc, heading):
    m = re.search(r"^##\s*%s\s*$(.*?)(?=^##\s|\Z)" % heading, desc or "",
                  re.M | re.S | re.I)
    if not m:
        return []
    return re.findall(r"`([^`\s]+)`", m.group(1))


def excerpt(text, start, end):
    """The lines from the first one matching `start` to the next one matching `end`, both included. None when `start` is not found."""
    lines = text.split("\n")
    for a, line in enumerate(lines):
        if re.search(start, line):
            for b in range(a + 1, len(lines)):
                if re.search(end, lines[b]):
                    return "\n".join(lines[a:b + 1])
            return "\n".join(lines[a:])
    return None


def build_prompt(i, files, context, excerpts=None):
    """`excerpts` is {path: [(start, end)]}: those files are sent in parts and must be changed with EDIT blocks."""
    excerpts = excerpts or {}
    parts = ["TASK %s: %s\n\n%s" % (i["identifier"], i["title"], i["description"])]
    for d in i["docs"]:
        parts.append("REFERENCE (Linear document: %s)\n%s" % (d["title"], d["content"]))
    for p in context:
        parts.append("CONTEXT, READ ONLY: %s\n%s" % (p, open(os.path.join(ROOT, p)).read()))
    parts.append("FILES YOU MAY CHANGE: %s" % ", ".join(files))
    for p in files:
        full = os.path.join(ROOT, p)
        body = open(full).read() if os.path.exists(full) else "(new file)"
        if p in excerpts:
            shown = [excerpt(body, s, e) for s, e in excerpts[p]]
            parts.append("FILE %s, SHOWN IN PARTS (%d characters in all; change it only with EDIT blocks)\n%s" % (
                p, len(body), "\n\n[...]\n\n".join(x for x in shown if x)))
        else:
            parts.append("FILE %s\n%s" % (p, body))
    return "\n\n=====\n\n".join(parts)


def too_big(files, excerpts):
    """Listed files over BIG_FILE characters with no excerpt: line, so they cannot be sent."""
    out = []
    for p in files:
        full = os.path.join(ROOT, p)
        if os.path.exists(full) and os.path.getsize(full) > BIG_FILE and p not in excerpts:
            out.append(p)
    return out


def call_model(messages, ident):
    try:
        return llm.complete(messages, models_to_try=MODELS, issue=ident, max_tokens=MAX_TOKENS)
    except llm.LLMError as e:
        raise Broken(str(e))


def clean(body):
    """Strip wrappers some models add around a file: a ``` fence at either
    end, or a stray </file> tag. qwen added `</file>` on 7 Oct (SEB-273),
    which made node --check fail on a file that was otherwise fine."""
    lines = body.split("\n")
    while lines and (lines[-1].strip() == "" or lines[-1].strip().lower() in ("</file>", "```")):
        lines.pop()
    while lines and (lines[0].strip() == "" or lines[0].strip().startswith("```")):
        lines.pop(0)
    return "\n".join(lines)


def apply_edits(text, allowed):
    """Apply the EDIT blocks. Returns (paths written, [why an edit could not be applied])."""
    written, errors = [], []
    for path, find, repl in re.findall(r"<<<EDIT ([^>\s]+)>>>\n<<<FIND>>>\n(.*?)\n<<<REPLACE>>>\n(.*?)\n?<<<END>>>", text, re.S):
        if path not in allowed:
            continue
        full = os.path.join(ROOT, path)
        body = open(full).read() if os.path.exists(full) else ""
        n = body.count(find)
        if n != 1:
            errors.append("EDIT %s: the FIND text occurs %d times in the file, it must occur exactly once" % (path, n))
            continue
        with open(full, "w") as f:
            f.write(body.replace(find, repl, 1))
        if path not in written:
            written.append(path)
    return written, errors


def apply(text, allowed, in_parts=()):
    """Write the FILE blocks, then apply the EDIT blocks. A file shown in parts is changed only by EDIT blocks."""
    blocks = re.findall(r"<<<FILE ([^>\s]+)>>>\n(.*?)\n<<<END>>>", text, re.S)
    written = []
    for path, body in blocks:
        if path not in allowed or path in in_parts:
            continue
        body = clean(body)
        if path.startswith("data/") and path.endswith(".csv"):
            body = body.split("\n")[0]        # a data file the builder lists is created with its header line only: rows come from real collections, never from a model
        with open(os.path.join(ROOT, path), "w") as f:
            f.write(body if body.endswith("\n") else body + "\n")
        written.append(path)
    more, errors = apply_edits(text, allowed)
    return written + [p for p in more if p not in written], errors


def run_checks(written):
    out = []
    cmds = (list(CHECKS) + [["node", "--check", p] for p in written if p.endswith(".js")]
            + [[sys.executable, "-m", "py_compile", p] for p in written if p.endswith(".py")]      # a Python file must at least compile
            + [[sys.executable, p, "--selftest"] for p in written                                  # a collector's own offline self-test
               if re.match(r"^collector[^/]*\.py$", p) and "--selftest" in open(os.path.join(ROOT, p)).read()])
    for c in cmds:
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            out.append("$ %s\n%s" % (" ".join(c), (r.stdout + r.stderr)[-1500:]))
    return out


def open_pr(i, written, rows):
    branch = i.get("branch") or "one-call/%s" % i["identifier"].lower()
    sh(["git", "checkout", "-q", "-B", branch])
    sh(["git", "add", "--"] + written)
    sh(["git", "commit", "-q", "-m", "%s\n\nOne-call runner, %s." % (
        i.get("pr_title") or "%s: %s" % (i["identifier"], i["title"]), ", ".join(r["model"] for r in rows))])
    sh(["git", "push", "-q", "-f", "origin", branch])
    repo = os.environ["GITHUB_REPOSITORY"]
    cost = sum(float(r["cost_usd"]) for r in rows)
    body = ("%s\n\n%s. %d call(s), $%.4f. Offline checks passed. "
            "The rendered check and screenshots run in CI.\n\n%s" % (
                i["url"], i.get("runner", "One-call runner"), len(rows), cost, "\n".join("- `%s`" % p for p in written)))
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/pulls" % repo,
        data=json.dumps({"title": i.get("pr_title") or "%s: %s" % (i["identifier"], i["title"]),
                         "head": branch, "base": "main", "body": body}).encode(),
        headers={"Authorization": "Bearer " + os.environ["GH_PUSH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["html_url"]
    except urllib.error.HTTPError as e:
        if e.code == 422:  # a PR for this branch is already open
            return "https://github.com/%s/pulls?q=head:%s" % (repo, branch)
        raise Broken("could not open PR: %s" % e.read().decode()[:300])


def run(ident):
    i = issue_with_docs(ident)
    return run_job(i)[0]


def run_job(i):
    """Build one job. Returns (rows, pr_url or None, why it stopped or ''). `i` is a Linear issue with `docs`, or a backlog job
    (see backlog_issue), which has no Linear issue to comment on or label."""
    files = paths_under(i["description"], "Files")
    context = paths_under(i["description"], "Context")
    excerpts = i.get("excerpts") or {}
    big = too_big(files, excerpts)
    if big:
        add_label(i, STUCK_LABEL)
        comment(i, "Too big to send whole and no excerpt given: %s. Labelled `needs-claude`." % ", ".join(big))
        return [], None, "too big to send whole, and the job gives no excerpt: line for " + ", ".join(big)
    if not files:
        add_label(i, STUCK_LABEL)
        comment(i, "No `## Files` section with backticked paths, so there is nothing "
                   "I may change. Labelled `needs-claude`.")
        return [], None, "no files listed"
    missing = [p for p in context if not os.path.exists(os.path.join(ROOT, p))]
    if missing:
        add_label(i, STUCK_LABEL)
        comment(i, "Context files not in the repo: %s. Labelled `needs-claude`." % ", ".join(missing))
        return [], None, "context files missing: " + ", ".join(missing)

    set_state(i, "In Progress")
    comment(i, "Starting. Files: %s." % ", ".join(files))
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": build_prompt(i, files, context, excerpts)}]
    rows, failures, written = [], [], []
    for attempt in range(MAX_CALLS):
        if spent_today() >= DAILY_CAP_USD:   # the file already holds this run's calls
            failures = ["daily cap of $%.2f reached" % DAILY_CAP_USD]
            break
        if sum(float(r["cost_usd"]) for r in rows) >= JOB_CAP_USD:
            failures = ["job cap of $%.2f reached" % JOB_CAP_USD]
            break
        chars = sum(len(m["content"]) for m in messages)
        if attempt and chars > llm.MAX_PROMPT_CHARS:
            failures.append("no retry: the retry prompt is %d characters, over the %d limit" % (chars, llm.MAX_PROMPT_CHARS))
            break
        text, row = call_model(messages, i["identifier"])
        rows.append(row)
        sh(["git", "checkout", "-q", "--"] + [p for p in files if os.path.exists(os.path.join(ROOT, p))], check=False)
        written, edit_errors = apply(text, set(files), set(excerpts))
        failures = edit_errors + (run_checks(written) if written else ["the model returned no files or edits in the agreed form"])
        if not failures:
            break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "The checks failed. Fix this and return "
                      "every changed file in full again:\n\n" + "\n\n".join(failures)}]

    cost = sum(float(r["cost_usd"]) for r in rows)
    if not failures:
        url = open_pr(i, written, rows)
        if i.get("backlog"):
            tick_on_branch(i, url)
        comment(i, "PR open: %s\n%d call(s), $%.4f." % (url, len(rows), cost))
        return rows, url, ""
    sh(["git", "checkout", "-q", "--", "."], check=False)
    add_label(i, STUCK_LABEL)
    comment(i, "Stopped after %d call(s), $%.4f. Labelled `needs-claude`.\n\n```\n%s\n```"
            % (len(rows), cost, "\n\n".join(failures)[-2500:]))
    return rows, None, "\n".join(failures)


# ---------- the daily backlog run (SEB-301, 20 Oct) ----------

def backlog_issue(item, job):
    """A backlog job shaped like the Linear issue the rest of this file works on."""
    desc = ["BACKLOG ITEM %s: %s" % (item["id"], item["title"]), "JOB %s: %s" % (job["id"], job["title"]), ""]
    if job["done_when"]:
        desc += ["DONE WHEN: " + job["done_when"], ""]
    if job["venues"]:
        desc += ["VENUES (the Scout fetched each one and read the real price field; use exactly these):"] + ["- " + v for v in job["venues"]] + [""]
    if job.get("excerpts"):
        desc += ["Some files are shown in parts because they are too big to send whole. Change those only with EDIT blocks.", ""]
    if "METHODOLOGY.md" in job["files"]:
        desc += ["This job changes how a published number is computed: describe the change in METHODOLOGY.md and bump INDEX_VERSION "
                 "(tools/emit_countries.py, and the other files that carry it) in the same change.", ""]
    desc += ["Real data only, never an invented number. A new data CSV you list is written with its header line ONLY, never a row. A new file runs only if its step is added to .github/workflows/collect.yml, by appending.", "",
             "## Files"] + ["`%s`" % p for p in job["files"]] + ["", "## Context"] + ["`%s`" % p for p in job["context"]]
    return {"backlog": True, "id": None, "identifier": BACKLOG_ISSUE + "/" + job["id"], "job": job["id"], "item": item["id"],
            "title": job["title"], "description": "\n".join(desc), "docs": [], "url": "BACKLOG.md job %s" % job["id"],
            "branch": "one-call/backlog-%s" % job["id"].lower(), "pr_title": "%s: %s (backlog %s)" % (BACKLOG_ISSUE, job["title"], job["id"]),
            "excerpts": {e[0]: [(x[1], x[2]) for x in job["excerpts"] if x[0] == e[0] and len(x) == 3] for e in job["excerpts"]},
            "collection": backlog.is_collection(job)}


def pr_number(url):
    m = re.search(r"/pull/(\d+)", url or "")
    return m.group(1) if m else None


def tick_on_branch(i, url):
    """Tick the job in BACKLOG.md with the PR number and today's date, as a second commit on the PR's own branch, so it lands only
    if the PR does. A collection job is not ticked: it gets `built: PR #N`, and is ticked only when its first rows are on main
    (rule d, tools/backlog.py verify-data)."""
    n = pr_number(url)
    if not n:
        return
    text = open(backlog.PATH).read()
    if i.get("collection"):
        open(backlog.PATH, "w").write(backlog.mark_built(text, i["job"], n, now().date().isoformat()))
        msg = "SEB-301: backlog job %s built, ticked when its first rows land (PR #%s)" % (i["job"], n)
    else:
        open(backlog.PATH, "w").write(backlog.tick(text, i["job"], n, now().date().isoformat()))
        msg = "SEB-301: tick backlog job %s (PR #%s)" % (i["job"], n)
    sh(["git", "add", "BACKLOG.md"])
    sh(["git", "commit", "-q", "-m", msg])
    sh(["git", "push", "-q", "-f", "origin", i["branch"]])


def ran_today(path=BUILDER_LOG, today=None):
    today = today or now().date().isoformat()
    if not os.path.exists(path):
        return False
    with open(path, newline="") as f:
        return any(r["ts_utc"][:10] == today for r in csv.DictReader(f))


def commit_main(log_rows, ops, message, log_path=None, log_header=None):
    """Put this run's bookkeeping on main: the spend rows, the builder log rows and any BACKLOG.md edits (re-applied to a fresh
    copy of main, so a concurrent change cannot be lost). Retries like commit_spend."""
    spend = list(llm.LOGGED)
    if (not spend and not log_rows and not ops) or os.environ.get("ONE_CALL_DRY_RUN"):
        return
    for attempt in range(3):
        sh(["git", "fetch", "-q", "origin", "main"])
        sh(["git", "checkout", "-q", "-f", "-B", "main", "origin/main"])
        paths = []
        if spend:
            llm.write_rows(spend)
            paths.append("data/agent_spend.csv")
        if log_rows:
            log_path = log_path or BUILDER_LOG
            new = not os.path.exists(log_path)
            with open(log_path, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(log_header or BUILDER_LOG_HEADER)
                w.writerows(log_rows)
            paths.append(os.path.relpath(log_path, ROOT))
        if ops:
            text = open(backlog.PATH).read()
            for op in ops:
                if op[0] == "block":
                    try:
                        text = backlog.block(text, op[1], op[2], now().date().isoformat())
                    except KeyError:
                        pass
                elif op[0] == "sync":
                    text, _ = backlog.sync(text, op[1])
            open(backlog.PATH, "w").write(text)
            paths.append("BACKLOG.md")
        sh(["git", "add"] + paths)
        if sh(["git", "diff", "--cached", "--quiet"], check=False).returncode == 0:
            return
        sh(["git", "commit", "-q", "-m", message])
        if sh(["git", "push", "-q", "origin", "main"], check=False).returncode == 0:
            return
    raise Broken("could not push the builder bookkeeping after 3 tries")


def gh_get(path):
    req = urllib.request.Request("https://api.github.com/repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path),
                                 headers={"Authorization": "Bearer " + os.environ["GH_PUSH_TOKEN"], "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def open_pr_state(branch, get=gh_get):
    """(number, 'pending' | 'failed') for an open PR from `branch`, or None. A job whose PR is already open is not built again."""
    owner = os.environ.get("GITHUB_REPOSITORY", "/").split("/")[0]
    prs = get("pulls?state=open&head=%s:%s" % (owner, branch))
    if not prs:
        return None
    sha = prs[0]["head"]["sha"]
    runs = get("commits/%s/check-runs?per_page=100" % sha)["check_runs"]
    bad = [r for r in runs if r["conclusion"] not in (None, "success", "skipped", "neutral")]
    return prs[0]["number"], ("failed" if bad else "pending")


def post_line(text):
    """One line on SEB-301 saying what the builder did."""
    try:
        i = linear.find(BACKLOG_ISSUE)
        linear.call("""mutation($id: String!, $b: String!) {
          commentCreate(input: { issueId: $id, body: $b }) { success }
        }""", {"id": i["id"], "b": "⚙️ **Builder:** " + text})
    except SystemExit:
        print("could not post on SEB-301", file=sys.stderr)


def backlog_run(force=False):
    """The daily run. Returns an exit code."""
    if not force and ran_today():
        print("the builder already ran today (data/builder_log.csv), nothing to do")
        return 0
    ts = now().isoformat()
    log_rows, ops, built = [], [], None
    # 1. copy new "Queued by Claude" items from SEB-301 comments into BACKLOG.md, and put them on main before any branch is cut
    try:
        comments = backlog.linear_comments()
        text, added = backlog.sync(open(backlog.PATH).read(), comments)
        if added:
            open(backlog.PATH, "w").write(text)
            commit_main([], [("sync", comments)], "SEB-301: %d item(s) queued by Claude copied into BACKLOG.md" % len(added))
            print("queued by Claude, copied into BACKLOG.md: " + "; ".join(added))
    except SystemExit as e:
        print("could not read SEB-301 comments: %s" % e, file=sys.stderr)
    text = open(backlog.PATH).read()
    tried = 0
    # 2. the top unchecked job with files; a job that fails twice is blocked and the next one is taken, up to MAX_JOBS_PER_RUN
    while tried < MAX_JOBS_PER_RUN:
        if spent_today() >= DAILY_CAP_USD:
            log_rows.append([ts, "nothing", "", "", "daily cap of $%.2f reached" % DAILY_CAP_USD])
            break
        nj = backlog.next_job(backlog.parse(text))
        if not nj:
            log_rows.append([ts, "nothing", "", "", "no job with files in BACKLOG.md (the Scout splits the next items on Mondays)"])
            break
        item, job = nj
        if backlog.is_collection(job) and not job["rows"]:
            why1 = "a collection job needs a rows: line saying where its first rows land (item 0, rule d)"
            ops.append(("block", job["id"], why1))
            text = backlog.block(text, job["id"], why1, now().date().isoformat())
            log_rows.append([ts, "failed", job["id"], "", why1])
            continue
        branch = "one-call/backlog-%s" % job["id"].lower()
        try:
            st = open_pr_state(branch)
        except Exception as e:       # noqa: BLE001 - not being able to look is not a reason to rebuild blindly
            print("could not look for an open PR for %s: %s" % (branch, e), file=sys.stderr)
            st = None
        if st and st[1] == "pending":
            print("job %s already has PR #%s open and its checks are still running: not built again" % (job["id"], st[0]))
            text = backlog.tick(text, job["id"], st[0], now().date().isoformat())        # in memory only: so the next job is taken
            continue
        if st:
            why1 = "its PR #%s failed its checks" % st[0]
            ops.append(("block", job["id"], why1))
            text = backlog.block(text, job["id"], why1, now().date().isoformat())
            log_rows.append([ts, "failed", job["id"], str(st[0]), why1])
            continue
        tried += 1
        print("backlog job %s: %s" % (job["id"], job["title"]))
        i = backlog_issue(item, job)
        sh(["git", "checkout", "-q", "main"], check=False)
        try:
            rows, url, why = run_job(i)
        except Broken as e:
            rows, url, why = [], None, str(e)
        if url:
            built = (job, url)
            log_rows.append([ts, "built", job["id"], pr_number(url) or "", job["title"]])
            break
        why1 = (why.strip().split("\n")[0] if why.strip() else "failed")[:200]
        ops.append(("block", job["id"], "failed: " + why1))
        text = backlog.block(text, job["id"], "failed: " + why1, now().date().isoformat())
        log_rows.append([ts, "failed", job["id"], "", why1])
    if built:
        post_line("built backlog job %s (%s), PR #%s." % (built[0]["id"], built[0]["title"], pr_number(built[1])))
    else:
        last = log_rows[-1][4] if log_rows else "nothing to do"
        post_line("built nothing today: %s." % last)
    commit_main(log_rows, ops, "one-call backlog run %s" % ts)
    return 0


def self_test():
    import tempfile
    items = backlog.parse("- [ ] 1. A route\n  - [ ] 1a. Add the collector\n    files: `collector_x.py` `.github/workflows/collect.yml`\n"
                          "    context: `METHODOLOGY.md`\n    venue: `THB` | `https://v.example/t` | `data.p`\n    done when: a row is written\n")
    item, job = backlog.next_job(items)
    i = backlog_issue(item, job)
    assert i["backlog"] and i["branch"] == "one-call/backlog-1a" and i["pr_title"] == "SEB-301: Add the collector (backlog 1a)"
    assert paths_under(i["description"], "Files") == ["collector_x.py", ".github/workflows/collect.yml"]
    assert paths_under(i["description"], "Context") == ["METHODOLOGY.md"]
    assert "data.p" in i["description"] and "DONE WHEN: a row is written" in i["description"]
    assert "bump INDEX_VERSION" not in i["description"]
    method = backlog_issue(item, dict(job, files=["METHODOLOGY.md", "tools/emit_countries.py"]))
    assert "bump INDEX_VERSION" in method["description"], "a method job is told to bump the version"
    probe = "data/_selftest_header_only.csv"
    try:
        got = apply("<<<FILE %s>>>\nts,a,b\n2026-10-20,1,2\n<<<END>>>" % probe, {probe})
        assert got == ([probe], []) and open(os.path.join(ROOT, probe)).read() == "ts,a,b\n", "a model's rows never reach a data CSV"
    finally:
        if os.path.exists(os.path.join(ROOT, probe)):
            os.remove(os.path.join(ROOT, probe))
    # a big file is sent in parts and changed only by edits (route jobs: collector.py is 103,000 characters)
    big = "\n".join(["# head"] * 3 + ["CORRIDORS = {", '    "A->B": {"x": 1},', "}", "def f():", "    return 1"])
    assert excerpt(big, r"^CORRIDORS = \{", r"^\}") == 'CORRIDORS = {\n    "A->B": {"x": 1},\n}'
    assert excerpt(big, r"^NOPE", r"^\}") is None
    rj = backlog.parse("- [ ] 1. R\n  - [ ] 1a. add C->D\n    files: `collector.py`\n    excerpt: `collector.py` `^CORRIDORS = \\{` `^\\}`\n"
                       "    rows: `data/samples.csv` `C->D`\n")
    ri = backlog_issue(rj[0], rj[0]["jobs"][0])
    assert ri["excerpts"] == {"collector.py": [(r"^CORRIDORS = \{", r"^\}")]} and ri["collection"] and "EDIT blocks" in ri["description"]
    assert too_big(["collector.py"], {}) == ["collector.py"] and too_big(["collector.py"], ri["excerpts"]) == []
    prompt = build_prompt(dict(ri, docs=[]), ["collector.py"], [], ri["excerpts"])
    assert "SHOWN IN PARTS" in prompt and '"SGD->PHP": {' in prompt and "def main():" not in prompt \
        and len(prompt) < len(open(os.path.join(ROOT, "collector.py")).read()) // 2  # parts, not the whole file; a fixed 30,000 broke on every new route (24 Oct)
    probe2 = "data/_selftest_edit.txt"
    try:
        open(os.path.join(ROOT, probe2), "w").write(big)
        edit = '<<<EDIT %s>>>\n<<<FIND>>>\n    "A->B": {"x": 1},\n<<<REPLACE>>>\n    "A->B": {"x": 1},\n    "C->D": {"x": 2},\n<<<END>>>' % probe2
        whole = "<<<FILE %s>>>\nwiped\n<<<END>>>\n" % probe2
        w, errs = apply(whole + edit, {probe2}, {probe2})
        after = open(os.path.join(ROOT, probe2)).read()
        assert w == [probe2] and not errs and '    "C->D": {"x": 2},\n}' in after and "wiped" not in after, "a part-shown file takes edits only"
        w, errs = apply('<<<EDIT %s>>>\n<<<FIND>>>\n# head\n<<<REPLACE>>>\nx\n<<<END>>>' % probe2, {probe2}, {probe2})
        assert w == [] and "occurs 3 times" in errs[0], "an edit whose text is not unique is refused"
    finally:
        if os.path.exists(os.path.join(ROOT, probe2)):
            os.remove(os.path.join(ROOT, probe2))
    assert pr_number("https://github.com/o/r/pull/561") == "561" and pr_number("https://github.com/o/r/pulls?q=head:x") is None
    comment(i, "no Linear issue to comment on")      # a backlog job has none: must not raise
    set_state(i, "Todo"); add_label(i, STUCK_LABEL)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "builder_log.csv")
        assert not ran_today(p, "2026-10-20")
        open(p, "w").write("ts_utc,status,job,pr,detail\n2026-10-20T06:00:00+00:00,built,1a,561,x\n")
        assert ran_today(p, "2026-10-20") and not ran_today(p, "2026-10-21")
    print("one_call self-test: ok")


def main():
    if "--self-test" in sys.argv:
        return self_test()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if "--backlog" in sys.argv:
        return backlog_run(force=True)
    if spent_today() >= DAILY_CAP_USD:
        print("daily cap of $%.2f reached, nothing run" % DAILY_CAP_USD)
        return 0
    ident = args[0] if args else next_ready()
    if not ident:
        print("no one-call issue ready; the backlog")
        return backlog_run(force=force)
    print("running %s" % ident)
    try:
        run(ident)
    except Broken as e:
        print("BROKEN: %s" % e, file=sys.stderr)
        try:
            i = linear.find(ident)
            add_label(i, STUCK_LABEL)
            comment(i, "Runner stopped: %s. Labelled `needs-claude`." % e)
        except SystemExit:
            pass
        commit_spend()
        return 1
    commit_spend()
    print("done: %d call(s), $%.4f" % (len(llm.LOGGED), sum(float(r["cost_usd"]) for r in llm.LOGGED)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
