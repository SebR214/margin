#!/usr/bin/env python3
"""The researcher (SEB-301, Seb's plan of 25 Oct). The only scheduled model that proposes work. One Sonnet call a week.

It reads the data-gap report (tools/gap_report.py, plain code), ROADMAP.md and the titles already in BACKLOG.md, and writes 8 jobs
to the end of BACKLOG.md, under "## Proposed by the researcher". Every job is held to the track A rules in tools/job_shape.py: new
files only (plus the source registry, which only grows), one new test tests/agent_<name>.py that `done when:` names,
and nothing that touches an existing collector, a page or a method. No new venue collector and no collect.yml change (27 Oct). A job that breaks a rule is refused by code, not queued. If fewer
than 3 pass, one more call gets the reasons. Never more than two calls a run. Seb's ideas and the chats' go in the same queue by hand.

    python3 tools/researcher.py               # run, unless it already ran this half-week (Mon to Wed, Thu to Sun)
    python3 tools/researcher.py --force       # run anyway
    python3 tools/researcher.py --dry-run     # one call, print the jobs and the checks, write nothing
    python3 tools/researcher.py --self-test

Log: data/researcher_log.csv (ts_utc,status,added,cost_usd,detail). Spend: data/agent_spend.csv, issue SEB-301/researcher.
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import backlog  # noqa: E402
import gap_report  # noqa: E402
import job_shape  # noqa: E402

LOG = os.path.join(ROOT, "data", "researcher_log.csv")
LOG_HEADER = ["ts_utc", "status", "added", "cost_usd", "detail"]
SECTION = "## Proposed by the researcher"
WANT = 8
ISSUE = "SEB-301/researcher"

RULES = """You are the researcher for margin.wiki. The site prices a dollar (USDT) against the official rate in about 60 countries
every hour, from real exchange and person-to-person data, and prices sending money on a few routes. The subject is the dollar premium:
where it exists, how sources disagree, how it opens and closes. Transfer apps are only benchmarks. It is not a comparison site.

Your job: propose exactly 8 jobs that close the biggest gaps in the gap report, in the spirit of ROADMAP.md. A cheap model (qwen) will
build each job alone, so every job must be small and mechanical.

Hard rules. Code checks every one and refuses a job that breaks it:
- files: only NEW files, plus at most one existing one that only grows: data/source_registry.json (add one source as "quarantine").
  Never any collector*.py (new or existing), never .github/workflows/collect.yml, never a page (.html, .js, .css, copy.json), never METHODOLOGY.md, DESIGN.md, ROADMAP.md, CLAUDE.md, BACKLOG.md, never an existing data CSV.
- Do not propose a new venue or exchange collector. The GitHub runners cannot reach most venues (Bybit and Quidax both failed on 27 Oct),
  so collection of a new venue is done by hand.
- Good shapes: a new analysis script (tools/) that reads existing CSVs and writes one new JSON or CSV in data/research/; a new sidecar
  CSV computed by a new tools/ script from existing CSVs; a new finding test file (findings_tests/).
- One test: files must include exactly one new tests/agent_<short_name>.py (lowercase, underscores), and "done_when" must name that
  path and say what it checks, with concrete inputs and expected results.
- context: existing files the builder may read, at most 4, from the file list given.
- No number is typed or guessed. Everything comes from files or live public endpoints read by code. No new API keys or accounts.
- Do not repeat a job already in the backlog titles.
- Each job cites the gap it closes in "gap", quoting the gap report entry (for example "one_source: THB").

Answer with JSON only, no prose:
{"jobs": [{"title": "...", "gap": "...", "files": ["..."], "context": ["..."], "rows": "data/... or empty", "done_when": "..."}]}"""


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def log_rows():
    if not os.path.exists(LOG):
        return []
    with open(LOG, newline="") as f:
        return list(csv.DictReader(f))


def log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow(row)


def half_week(t):
    """(ISO year, ISO week, 0 for Monday to Wednesday or 1 for Thursday to Sunday). The researcher runs once in each half."""
    y, w, d = t.isocalendar()
    return (y, w, 0 if d <= 3 else 1)


def ran_recently(rows, at):
    """True when an ok run is already logged in the same half-week as `at`. A hand run on a Sunday no longer eats the next
    Monday's run (it did on 26 Oct, when the 25 Oct test run blocked the week)."""
    for r in rows:
        if r["status"] == "ok" and half_week(datetime.datetime.fromisoformat(r["ts_utc"])) == half_week(at):
            return True
    return False


def file_list():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    keep = [p for p in out if re.match(r"^(collector[^/]*\.py|tools/[^/]+\.py|tests/[^/]+\.py|data/[^/]+\.(csv|json)|findings_tests/.*)$", p)]
    return keep


def queue_titles(text):
    out = []
    for it in backlog.parse(text):
        out.append("%s. %s%s" % (it["id"], "[done] " if it["done"] else "", it["title"][:140]))
        for j in it["jobs"]:
            out.append("  %s. %s%s" % (j["id"], "[done] " if j["done"] else "", j["title"][:140]))
    return out


def trim(report):
    r = dict(report)
    r["disagree"] = report["disagree"][:25]
    r["disagree_total"] = len(report["disagree"])
    return r


def prompt(report, roadmap, titles, files, problems=None):
    parts = ["GAP REPORT (computed by code from the CSVs):\n" + json.dumps(trim(report), indent=0)[:30000],
             "ROADMAP.md:\n" + roadmap[:8000],
             "ALREADY IN THE BACKLOG:\n" + "\n".join(titles)[:12000],
             "FILES THAT EXIST (names only):\n" + "\n".join(files)[:20000]]
    if problems:
        parts.append("YOUR LAST ANSWER BROKE THESE RULES. Answer again with 8 jobs that pass:\n" + "\n".join(problems))
    return [{"role": "system", "content": RULES}, {"role": "user", "content": "\n\n".join(parts)}]


def parse_answer(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        jobs = json.loads(m.group(0)).get("jobs") or []
    except ValueError:
        return []
    return [j for j in jobs if isinstance(j, dict)]


MENTIONED = re.compile(r"\b((?:data|tools|tests|findings_tests)/[\w./-]+\.(?:py|json|csv)|collector_\w+\.py)\b")


def check(job, titles, exists=None, taken_files=()):
    exists = exists or (lambda p: os.path.exists(os.path.join(ROOT, p)))
    j = {"files": [str(p) for p in job.get("files") or []], "done_when": str(job.get("done_when") or "")}
    why = job_shape.researcher_problems(j, exists)
    for p in sorted(set(MENTIONED.findall(j["done_when"]))):
        if not exists(p) and p not in j["files"]:
            why.append("done when writes %s but files does not list it" % p)
    for p in j["files"]:
        if p in taken_files and p not in job_shape.APPEND_OK:
            why.append("%s is already a file of another open job" % p)
    title = str(job.get("title") or "").strip()
    if len(title) < 10:
        why.append("title missing")
    low = title.lower()
    if any(low and low in t.lower() for t in titles):
        why.append("already in the backlog")
    if not str(job.get("gap") or "").strip():
        why.append("no gap cited")
    for p in job.get("context") or []:
        if not exists(str(p)):
            why.append("context %s does not exist" % p)
    if len(job.get("files") or []) > 5:
        why.append("more than 5 files")
    collection = backlog.is_collection(j)
    rows = str(job.get("rows") or "").strip()
    if collection and not (rows and rows in j["files"] and rows.endswith(".csv")):
        why.append("a collection job needs rows: one of its new CSVs in files")
    for c in ("`", "\n"):
        if c in title or c in j["done_when"]:
            why.append("no backticks or line breaks in title or done when")
    return sorted(set(why))


def render(text, jobs, today):
    """Append the jobs to BACKLOG.md under SECTION, one new item each, numbered after the highest item."""
    items = backlog.parse(text)
    n = max([int(i["id"]) for i in items] or [0])
    lines = []
    for job in jobs:
        n += 1
        files = " ".join("`%s`" % p for p in job["files"])
        lines += ["- [ ] %d. %s" % (n, job["title"].strip()),
                  "  - [ ] %da. %s" % (n, job["title"].strip()),
                  "    track: aider",
                  "    proposed: researcher %s (gap: %s)" % (today, str(job["gap"]).strip()[:160].replace("\n", " ")),
                  "    files: %s" % files]
        if job.get("context"):
            lines.append("    context: %s" % " ".join("`%s`" % p for p in job["context"]))
        if backlog.is_collection(job):
            lines.append("    rows: `%s`" % job["rows"].strip())
        lines.append("    done when: %s" % job["done_when"].strip())
    text = text.rstrip("\n") + "\n"
    if SECTION not in text:
        text += "\n" + SECTION + "\n" + "Written by tools/researcher.py, one Sonnet call a week. Track A rules in tools/job_shape.py.\n\n"
    return text + "\n".join(lines) + "\n"


def run(dry, force):
    import llm
    at = now()
    if not force and ran_recently(log_rows(), at):
        print("the researcher already ran this half-week (data/researcher_log.csv), nothing to do")
        return 0
    report = gap_report.build(at)
    if not dry:
        with open(gap_report.OUT, "w") as f:
            json.dump(report, f, indent=1)
            f.write("\n")
    print(gap_report.summary(report))
    text = open(backlog.PATH).read()
    titles = queue_titles(text)
    taken_files = {p for it in backlog.parse(text) for jb in it["jobs"] if not jb["done"] for p in jb["files"]}
    roadmap = open(os.path.join(ROOT, "ROADMAP.md")).read()
    files = file_list()
    model = llm.resolve_sonnet()
    good, problems, cost = [], None, 0.0
    for attempt in (1, 2):
        try:
            out, row = llm.complete(prompt(report, roadmap, titles, files, problems), models_to_try=[model], issue=ISSUE,
                                    max_tokens=7000)
        except llm.LLMError as e:
            if not dry:
                log([at.isoformat(timespec="seconds"), "failed", 0, "%.6f" % cost, str(e)[:200]])
            print("researcher: %s" % e, file=sys.stderr)
            return 1
        cost += float(row["cost_usd"])
        problems = []
        taken = titles + ["%s" % j["title"] for j in good]
        for j in parse_answer(out):
            why = check(j, taken, taken_files=taken_files | {p for g in good for p in g["files"]})
            if why:
                problems.append("%s: %s" % (str(j.get("title"))[:80], "; ".join(why)))
            elif len(good) < WANT:
                good.append(j)
                taken.append(j["title"])
        print("call %d: %d passed, %d refused" % (attempt, len(good), len(problems)))
        for p in problems:
            print("  refused: " + p)
        if len(good) >= WANT:
            break
    for j in good:
        print("  + %s\n    files: %s\n    done when: %s" % (j["title"], " ".join(j["files"]), j["done_when"]))
    if dry:
        print("dry run: nothing written ($%.4f)" % cost)
        return 0
    if good:
        with open(backlog.PATH, "w") as f:
            f.write(render(text, good, at.date().isoformat()))
    status = "ok" if good else "failed"
    log([at.isoformat(timespec="seconds"), status, len(good), "%.6f" % cost,
         ("added: " + " | ".join(j["title"][:60] for j in good)) if good else ("nothing passed: " + " | ".join(problems)[:300])])
    return 0 if good else 1


def self_test():
    have = {"collector.py", ".github/workflows/collect.yml", "data/source_pairs.json", "data/source_registry.json", "data/p2p_okx.csv"}
    ex = have.__contains__
    ok = {"title": "Which side carries the gap for each disagreeing pair", "gap": "disagree: THB",
          "files": ["tools/diagnose_gap_side.py", "data/research/gap_side.json", "tests/agent_gap_side.py"],
          "context": ["data/source_pairs.json"], "rows": "",
          "done_when": "python3 tests/agent_gap_side.py runs tools/diagnose_gap_side.py on inline rows and gets one side label per pair"}
    assert check(ok, [], ex) == [], check(ok, [], ex)
    venue = dict(ok, title="Bitkub THB order book as a second THB source", gap="one_source: THB",
                 files=["collector_bitkub_thb.py", ".github/workflows/collect.yml", "data/bitkub_thb.csv", "tests/agent_bitkub_thb.py"],
                 rows="data/bitkub_thb.csv", done_when="python3 tests/agent_bitkub_thb.py runs collector_bitkub_thb.py --selftest on a stored book and gets one row")
    w = check(venue, [], ex)
    assert any("new collector" in x for x in w) and any("collect.yml" in x for x in w), w
    assert "already in the backlog" in check(ok, ["40. Which side carries the gap for each disagreeing pair"], ex)
    assert any("existing collector" in w for w in check(dict(ok, files=["collector.py", "tests/agent_x.py"]), [], ex))
    assert "no gap cited" in check(dict(ok, gap=""), [], ex)
    assert "context nope.py does not exist" in check(dict(ok, context=["nope.py"]), [], ex)
    w = check(dict(ok, done_when=ok["done_when"] + " and writes data/research/summary.json"), [], ex)
    assert "done when writes data/research/summary.json but files does not list it" in w, w
    assert "tools/diagnose_gap_side.py is already a file of another open job" in check(ok, [], ex, {"tools/diagnose_gap_side.py"})
    a = parse_answer('Here: {"jobs": [{"title": "x"}]} done')
    assert a == [{"title": "x"}] and parse_answer("no json") == [] and parse_answer("{bad json}") == []
    text = "# Build backlog\n\n## Routes\n- [ ] 3. A\n  - [ ] 3a. A\n    files: `a.py`\n- [x] 19. B\n"
    out = render(text, [ok], "2026-10-26")
    items = backlog.parse(out)
    assert items[-1]["id"] == "20" and items[-1]["jobs"][0]["id"] == "20a", items[-1]
    j = items[-1]["jobs"][0]
    assert j["track"] == "aider" and j["files"] == ok["files"] and "agent_gap_side" in j["done_when"]
    assert "proposed: researcher 2026-10-26 (gap: disagree: THB)" in out and out.count(SECTION) == 1
    again = render(out, [dict(ok, title="Another job that is long enough")], "2026-11-02")
    assert again.count(SECTION) == 1 and backlog.parse(again)[-1]["id"] == "21"
    t0 = datetime.datetime(2026, 10, 26, 2, tzinfo=datetime.timezone.utc)
    assert ran_recently([{"status": "ok", "ts_utc": "2026-10-26T00:20:00+00:00"}], t0), "already ran this Monday"
    assert not ran_recently([{"status": "ok", "ts_utc": "2026-10-25T03:26:00+00:00"}], t0), "a Sunday run is last week"
    thu = datetime.datetime(2026, 10, 29, 2, tzinfo=datetime.timezone.utc)
    assert not ran_recently([{"status": "ok", "ts_utc": "2026-10-26T00:20:00+00:00"}], thu), "Monday's run does not block Thursday"
    assert ran_recently([{"status": "ok", "ts_utc": "2026-10-29T00:20:00+00:00"}], thu)
    assert not ran_recently([{"status": "failed", "ts_utc": "2026-10-25T02:00:00+00:00"}], t0), "a failed run is retried"
    msgs = prompt(gap_report.build(t0), "roadmap", ["1. x"], ["tools/a.py"])
    assert sum(len(m["content"]) for m in msgs) < 100000, "the prompt stays small"
    print("researcher self-test: ok")


def main(argv):
    if "--self-test" in argv:
        self_test()
        return 0
    return run("--dry-run" in argv, "--force" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
