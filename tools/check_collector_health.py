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

SAMPLE_RE = re.compile(r"^sample (\d{4}-\d{2}-\d{2}T\d{2}:\d{2})Z?", re.MULTILINE)


def run(cmd):
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, check=True).stdout


def last_sample_commit_age_minutes(now):
    """Minutes since the newest commit on main whose message is a chain
    "sample <ts>" commit -- the chain's own heartbeat, independent of the
    hotfix/feature commits that sit on top of it."""
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


def recent_run_conclusions():
    """Most recent RUN_LOOKBACK collect.yml runs, newest first, as a list of
    conclusion strings ("success", "failure", or "" for still-running)."""
    out = run([
        "gh", "api",
        f"repos/{REPO}/actions/workflows/collect.yml/runs"
        f"?per_page={RUN_LOOKBACK}&exclude_pull_requests=true",
    ])
    data = json.loads(out)
    return [
        (r.get("conclusion") or r.get("status") or "")
        for r in data.get("workflow_runs", [])
    ]


def leading_consecutive_failures(conclusions):
    """How many of the newest runs failed with nothing but failures between
    them and the last success (or the start of the window)."""
    n = 0
    for c in conclusions:
        if c == "failure":
            n += 1
        elif c == "success":
            break
        # in_progress / queued / cancelled: skip, neither confirms nor breaks
        # the streak -- an in-flight run tells us nothing yet either way.
    return n


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
    main()
