#!/usr/bin/env python3
"""What a track A job may touch (SEB-301, Seb's plan of 25 Oct). No model, no network.

A cheap builder is only useful on jobs it can't get wrong. So:

- track B only: any job that changes collector.py or another existing collector file, a page (html, js, css, copy.json), or a method
  (METHODOLOGY.md, DESIGN.md). The Aider builder never takes one (`forbidden`). Those are built in Seb's own sessions.
- researcher jobs are stricter (`researcher_problems`): new files only, plus collect.yml (it only grows, tools/check_additive.py) and
  the source registry (a new row). Each job lists a new test, `tests/agent_<something>.py`, and its `done when:` names it. That test
  runs in CI and as the builder's own test (tools/run_agent_tests.py).

    python3 tools/job_shape.py              # list every open job the builder may not take, and why
    python3 tools/job_shape.py --self-test
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Existing files a researcher job may change: both only grow, and the checks hold them to that.
APPEND_OK = {".github/workflows/collect.yml", "data/source_registry.json"}
TEST = re.compile(r"^tests/agent_[a-z0-9_]+\.py$")
PAGE = re.compile(r"(\.html|\.css|^js/.*\.js|^copy\.json)$")
METHOD = {"METHODOLOGY.md", "DESIGN.md", "ROADMAP.md", "CLAUDE.md", "BACKLOG.md"}


def forbidden(files, exists=None):
    """Reasons a job is track B. Empty list: the builder may take it."""
    exists = exists or (lambda p: os.path.exists(os.path.join(ROOT, p)))
    out = []
    for p in files:
        if re.match(r"^collector[^/]*\.py$", p) and exists(p):
            out.append("%s is an existing collector" % p)
        elif PAGE.search(p):
            out.append("%s is a page" % p)
        elif p in METHOD:
            out.append("%s is a method or rule file" % p)
    return out


def researcher_problems(job, exists=None):
    """Reasons a researcher job is refused. Empty list: it goes in the queue."""
    exists = exists or (lambda p: os.path.exists(os.path.join(ROOT, p)))
    files = job.get("files") or []
    out = forbidden(files, exists)
    if not files:
        out.append("no files listed")
    for p in files:
        if exists(p) and p not in APPEND_OK and not PAGE.search(p) and p not in METHOD:
            out.append("%s already exists (new files only)" % p)
        if p.startswith("data/") and p.endswith(".csv") and exists(p):
            out.append("%s is an existing CSV (headers are frozen)" % p)
    tests = [p for p in files if TEST.match(p)]
    if not tests:
        out.append("no new test file tests/agent_<name>.py in files")
    elif not any(t in (job.get("done_when") or "") for t in tests):
        out.append("done when does not name the test %s" % tests[0])
    if len(job.get("done_when") or "") < 40:
        out.append("done when is too short to test")
    return sorted(set(out))


def self_test():
    have = {"collector.py", "collector_providers.py", ".github/workflows/collect.yml", "data/p2p_basis.csv",
            "data/source_registry.json", "tools/emit_routes.py"}
    ex = have.__contains__
    assert forbidden(["collector.py"], ex) and forbidden(["index.html"], ex) and forbidden(["copy.json"], ex)
    assert forbidden(["METHODOLOGY.md"], ex) and forbidden(["js/route.js"], ex)
    assert not forbidden(["collector_new_venue.py", "tools/x.py", ".github/workflows/watchdog.yml"], ex), "a new collector is fine"
    good = {"files": ["collector_bitkub.py", ".github/workflows/collect.yml", "tests/agent_bitkub.py"],
            "done_when": "python3 tests/agent_bitkub.py passes: collector_bitkub.py --selftest parses a stored order book and writes one row"}
    assert researcher_problems(good, ex) == [], researcher_problems(good, ex)
    assert any("already exists" in r for r in researcher_problems(dict(good, files=good["files"] + ["tools/emit_routes.py"]), ex))
    assert any("existing CSV" in r for r in researcher_problems(dict(good, files=good["files"] + ["data/p2p_basis.csv"]), ex))
    assert any("existing collector" in r for r in researcher_problems(dict(good, files=["collector.py", "tests/agent_x.py"]), ex))
    assert any("no new test" in r for r in researcher_problems(dict(good, files=["collector_bitkub.py"]), ex))
    assert any("does not name" in r for r in researcher_problems(dict(good, done_when="it works and writes rows to a new file ok"), ex))
    print("job_shape self-test: ok")


def main(argv):
    if "--self-test" in argv:
        self_test()
        return 0
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import backlog
    for it in backlog.parse(open(backlog.PATH).read()):
        for j in it["jobs"]:
            if j["done"]:
                continue
            why = forbidden(j["files"])
            if why:
                print("%s track B: %s" % (j["id"], "; ".join(why)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
