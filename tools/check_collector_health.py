#!/usr/bin/env python3
"""Is the collect.yml chain actually alive, from OUTSIDE the chain itself?

check_freshness.py answers "is the newest row recent enough?" but it runs AS A
STEP of collect.yml -- if the job dies before reaching that step (exactly what
happened 2026-09-26, when a schema mismatch broke tools/emit_bundle.py and
killed the job before any freshness check ran), the guard never fires and
nothing outside the Actions tab ever finds out. Nobody was watching the
Actions tab; the outage ran ~3.5 hours and was only caught because a human
asked for a status update.

This is the outside check. It has no dependency on collect.yml completing --
it reads the workflow's own run history via `gh api` and the repo's commit
log, both independent of whether the last run finished. Exit 0 = healthy.
Exit 1 = unhealthy, with the reason on stderr, meant for something (a CI
watchdog, a scheduled agent) that actually alerts a human -- this script only
measures and reports, it never pages anyone itself.

Unhealthy means either:
  - the last STALE_MINUTES minutes produced no commit whose message matches
    the "sample <ISO timestamp>" pattern the chain uses, or
  - MAX_CONSECUTIVE_FAILURES or more of the most recent collect.yml runs
    (oldest-first among the recent page) completed with conclusion=failure
    back to back, with no success in between.
A run also counts as down when its "Commit samples" step failed (31 Oct, after 28 Oct 21:05 UTC when a file over 100 MB made every
push fail): the run's own conclusion is not trusted on its own. A run that never reached that step (a scheduled fire that finds
the chain already alive and exits) says nothing either way and no longer counts as a success that ends a streak of failures.
Either condition alone is what a genuinely dead chain looks like; either one
alone can also be a single bad-luck run, which is why both use a small run of
consecutive evidence rather than one data point.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("GH_REPO", "SebR214/margin")

STALE_MINUTES = float(os.environ.get("COLLECTOR_STALE_MINUTES", "60"))
MAX_CONSECUTIVE_FAILURES = int(os.environ.get("COLLECTOR_MAX_CONSECUTIVE_FAILURES", "2"))
RUN_LOOKBACK = 8
COMMIT_STEP = "Commit samples"

SAMPLE_RE = re.compile(r"^sample (\d{4}-\d{2}-\d{2}T\d{2}:\d{2})Z?", re.MULTILINE)


def run(cmd):
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, check=True).stdout


def last_sample_commit_age_minutes(now):
    """Minutes since the newest commit on main whose message is a chain
    "sample <ts>" commit -- the chain's own heartbeat, independent of the
    hotfix/feature commits that sit on top of it."""
    try:
        run(["git", "fetch", "origin", "main"])
    except subprocess.CalledProcessError as e:
        print(f"  [warn] could not fetch origin/main, using local ref: {e.stderr.strip()}",
              file=sys.stderr)
    log = run(["git", "log", "origin/main", "--format=%H %aI %s", "-n", "200"])
    for line in log.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        _, iso, subject = parts
        if subject.startswith("sample "):
            ts = dt.datetime.fromisoformat(iso)
            return (now - ts.astimezone(dt.timezone.utc)).total_seconds() / 60
    return None  # no sample commit found at all in the lookback window


def commit_step_conclusion(run_id):
    """The conclusion of the "Commit samples" step of one run ("success", "failure", "skipped"), or None when it cannot be read
    or the run has no such step."""
    try:
        out = run(["gh", "api", f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100"])
        for job in json.loads(out).get("jobs", []):
            for step in job.get("steps", []):
                if step.get("name") == COMMIT_STEP:
                    return step.get("conclusion")
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    return None


def effective_conclusion(conclusion, commit):
    """What one run counts as. "failure" when its Commit samples step failed, whatever the run says; None (counts as nothing) for
    a successful run that skipped the step, because it never collected; otherwise the run's own conclusion."""
    if commit == "failure":
        return "failure"
    if commit == "skipped" and conclusion == "success":
        return None
    return conclusion


def usable_conclusions(runs, limit=RUN_LOOKBACK, commit_of=None):
    """Filter runs to only include completed successes and failures.
    Drops cancelled, skipped, queued, in-progress and empty-conclusion runs. With commit_of (run id -> the Commit samples step's
    conclusion) a run whose commit failed counts as a failure and a successful run that skipped the commit is dropped."""
    conclusions = []
    for r in runs:
        conclusion = r.get("conclusion")
        if conclusion not in ("success", "failure"):
            continue
        if commit_of is not None:
            conclusion = effective_conclusion(conclusion, commit_of(r.get("id")))
            if conclusion is None:
                continue
        conclusions.append(conclusion)
        if len(conclusions) >= limit:
            break
    return conclusions


def recent_run_conclusions():
    """Most recent RUN_LOOKBACK collect.yml runs, newest first, as a list of
    conclusion strings ("success", "failure"). Drops cancelled, skipped,
    queued, in-progress and empty-conclusion runs."""
    out = run([
        "gh", "api",
        f"repos/{REPO}/actions/workflows/collect.yml/runs"
        f"?per_page=30&exclude_pull_requests=true",
    ])
    data = json.loads(out)
    runs = data.get("workflow_runs", [])
    return usable_conclusions(runs, commit_of=commit_step_conclusion)


def leading_consecutive_failures(conclusions):
    """How many of the newest runs failed with nothing but failures between
    them and the last success (or the start of the window).
    Only 'failure' increments the count. 'success' stops the count.
    Every other value (cancelled, in_progress, queued, '', etc.) is ignored.
    It neither counts nor breaks the streak."""
    n = 0
    for c in conclusions:
        if c == "failure":
            n += 1
        elif c == "success":
            break
        # cancelled / in_progress / queued / '': ignore, neither confirms nor breaks
        # the streak -- an ignored run tells us nothing yet either way.
    return n


def self_test():
    runs = [{"id": i, "conclusion": c} for i, c in enumerate(
        ["failure", "success", "failure", "cancelled", "success", "failure"])]
    plain = usable_conclusions(runs)
    assert plain == ["failure", "success", "failure", "success", "failure"], plain
    assert leading_consecutive_failures(plain) == 1, "old behaviour: a no-op success ends the streak"
    steps = {0: "failure", 1: "skipped", 2: "failure", 4: "success", 5: "failure"}
    got = usable_conclusions(runs, commit_of=steps.get)
    assert got == ["failure", "failure", "success", "failure"], got
    assert leading_consecutive_failures(got) == 2, "a no-op fire in between no longer hides two failed commits"
    assert effective_conclusion("success", "failure") == "failure", "the run says success, its commit failed: down"
    assert effective_conclusion("success", "success") == "success"
    assert effective_conclusion("success", None) == "success", "step not readable: trust the run"
    assert effective_conclusion("failure", "skipped") == "failure"
    assert effective_conclusion("success", "skipped") is None
    only = [{"id": 9, "conclusion": "success"}]
    assert usable_conclusions(only, commit_of=lambda i: "failure") == ["failure"]
    assert usable_conclusions([{"id": i, "conclusion": "failure"} for i in range(20)], limit=3, commit_of=lambda i: "failure") == ["failure"] * 3
    print("check_collector_health self-test: ok")
    return 0


def main():
    now = dt.datetime.now(dt.timezone.utc)
    reasons = []

    age = last_sample_commit_age_minutes(now)
    if age is None:
        reasons.append("no 'sample <ts>' commit found in the last 200 commits at all")
    else:
        mark = "ok" if age <= STALE_MINUTES else "STALE"
        print(f"  [{mark}] last chain commit {age:.0f} min ago (limit {STALE_MINUTES:.0f})")
        if age > STALE_MINUTES:
            reasons.append(f"last chain commit {age:.0f} min ago, limit {STALE_MINUTES:.0f}")

    try:
        conclusions = recent_run_conclusions()
    except subprocess.CalledProcessError as e:
        print(f"  [warn] could not read run history: {e.stderr.strip()}", file=sys.stderr)
        conclusions = []
    except FileNotFoundError:
        print("  [warn] could not read run history: 'gh' CLI not found", file=sys.stderr)
        conclusions = []

    if conclusions:
        streak = leading_consecutive_failures(conclusions)
        mark = "ok" if streak < MAX_CONSECUTIVE_FAILURES else "STALE"
        print(f"  [{mark}] {streak} consecutive failing run(s) (limit {MAX_CONSECUTIVE_FAILURES})"
              f" -- recent: {conclusions}")
        if streak >= MAX_CONSECUTIVE_FAILURES:
            reasons.append(f"{streak} consecutive collect.yml failures: {conclusions}")

    if reasons:
        print(f"\n  [error] collector chain looks down -- {'; '.join(reasons)}", file=sys.stderr)
        sys.exit(1)
    print("\n  collector chain healthy")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    main()
