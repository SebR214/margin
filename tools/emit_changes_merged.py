#!/usr/bin/env python3
"""How many changes actually merged into main in the trailing 7 days.

how-it-was-built.html's stat tiles claim a "changes merged this week" figure.
Per DESIGN.md ("Numbers are computed from data/, never typed"), that number
has to come from a real source, not a guess -- this script computes it from
this repo's own git history and writes data/changes_merged.json, which the
page fetches at runtime.

This repo merges every PR by squash, onto main, as a single linear commit
(confirmed against git history: no merge commits since #73, and recent
commits each carry a "(#NNN)" PR-number suffix in their subject line --
see docs/MERGE-LOG.md). So "a change merged" == "a commit on main whose
subject line ends in (#NNN)". Commits without that suffix are not a merged
PR: they're either this script's own sample/test commits or a direct push,
and counting them would overstate what agents actually shipped.

The window is a trailing 7*24h from the newest commit's own timestamp, not
wall-clock "now" -- so a stale checkout (or CI running hours after the last
commit) still reports the real window that commit history covers, the same
convention tools/agent_status.py uses ("judged day is the day before the
newest one in the data").

Stdlib only (git via subprocess, no network, no GitHub API -- this repo's
own commit log already has everything this figure needs).

Usage: python3 tools/emit_changes_merged.py
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "changes_merged.json")

WINDOW_DAYS = 7
PR_SUFFIX_RE = re.compile(r"\(#\d+\)\s*$")


def git_log():
    """(iso_timestamp, subject) for every commit reachable from HEAD, newest first."""
    out = subprocess.check_output(
        ["git", "log", "--pretty=format:%H\x1f%cI\x1f%s"],
        cwd=HERE,
    ).decode("utf-8", "replace")
    rows = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        sha, iso, subject = parts
        rows.append((sha, iso, subject))
    return rows


def main():
    commits = git_log()
    if not commits:
        print("emit_changes_merged: no commits found (not a git checkout?)", file=sys.stderr)
        return 1

    newest_iso = commits[0][1]
    newest_dt = dt.datetime.fromisoformat(newest_iso)
    window_start = newest_dt - dt.timedelta(days=WINDOW_DAYS)

    merged = []
    for sha, iso, subject in commits:
        c_dt = dt.datetime.fromisoformat(iso)
        if c_dt < window_start:
            break  # git log is newest-first, so nothing after this is in-window
        if PR_SUFFIX_RE.search(subject):
            merged.append({"sha": sha[:9], "merged_at_utc": iso, "subject": subject})

    doc = {
        "count": len(merged),
        "window_days": WINDOW_DAYS,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc": newest_iso,
        "commits": merged,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")

    print(f"emit_changes_merged: {len(merged)} PRs merged in trailing {WINDOW_DAYS}d "
          f"(window {window_start.isoformat()} .. {newest_iso})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
