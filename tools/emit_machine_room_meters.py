#!/usr/bin/env python3
"""SEB-174/M2: the three "where things stand" meters the-machine-room.html
cannot compute itself, because computing them needs something a static page
in a browser cannot do -- run `git log` locally, or call the GitHub API with
a token.

M1's own docstring (tools/serve_events.py) already ruled out doing this
inside the public SSE process: "handing this publicly-reachable process a
GitHub credential is a bigger hole than the gap it would close... Left for
M2 to source another way (a periodic sidecar, not this stream)." This is
that sidecar -- it runs where collect.yml already runs, with the token
GitHub Actions already hands that job, and writes a small JSON file the page
reads like any other data/ file.

Three numbers, each read the way the issue named:

  collector_commits_today -- git log on this checkout's current branch,
    same local command serve_events.py's own `_commit_events` already runs
    (no GitHub API, no token). "Collector commit" means a commit with no
    "(#NNN)" suffix on its subject -- the hourly "sample ..." / "fee check
    ..." commits, not a squash-merged PR (same distinction
    how-it-was-built.html's isShippedCommit draws, inverted: that page
    excludes collector commits from "shipped"; this one counts only those).
    "Today" is the commit's own UTC date, not wall-clock now, so a run
    slightly after midnight UTC still reports the day the commits actually
    landed in.

  open_pull_requests -- `gh pr list --state open`, literally, as the issue
    names it. Needs GH_TOKEN in the environment (collect.yml already sets
    this for its other `gh` steps); falls back to the public, unauthenticated
    REST endpoint if `gh` is not on PATH, which is enough for a local
    by-hand run.

  unbroken_hours -- the same measurement tools/check_delivery.py makes
    (DISTINCT UTC hours present in data/basis.csv and data/p2p_basis.csv --
    see that script's own docstring), turned into one number instead of its
    14-day table: counting backward from the most recent hour either file
    actually has a row for (not wall-clock now -- the 30-minute collection
    cadence means the current hour routinely has no row yet), how many
    consecutive hours have at least one row in BOTH files. Both, not either,
    for the same reason check_delivery.py reports the two files separately
    rather than their union -- "a day where one delivered 23 hours and the
    other 4 is a real and useful thing to see... reporting only their union
    would hide it." An "unbroken" streak that only required one of the two
    collectors to have fired would be just as misleading.

Writes data/machine_room_meters.json. Never fabricates a number it cannot
compute: a step that fails leaves its field null rather than guessing, and
is announced on stderr -- the same "gaps stay gaps" rule as every collector
here, applied to a meter about the collectors instead of about a price.

Stdlib only (gh, if present, is invoked as a subprocess; no library needs it).

Usage: python3 tools/emit_machine_room_meters.py
"""

import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "machine_room_meters.json")

REPO = "SebR214/margin"
PR_SUFFIX_RE = re.compile(r"\(#\d+\)\s*$")
DELIVERY_FILES = ["basis.csv", "p2p_basis.csv"]


def collector_commits_today():
    """Commits on HEAD today (UTC) with no "(#NNN)" suffix -- a collector
    pass, not a merged PR. None on any failure; never a guessed count.
    """
    try:
        out = subprocess.run(
            ["git", "-C", HERE, "log", "--format=%cI%x1f%s", "-500"],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        print("emit_machine_room_meters: git log failed", file=sys.stderr)
        return None
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    count = 0
    for line in out.strip("\n").split("\n"):
        if not line:
            continue
        iso, subject = line.split("\x1f", 1)
        try:
            when = dt.datetime.fromisoformat(iso)
        except ValueError:
            continue
        if when.astimezone(dt.timezone.utc).date().isoformat() != today:
            continue
        if not PR_SUFFIX_RE.search(subject):
            count += 1
    return count


def open_pull_requests():
    """`gh pr list --state open`, counted. Falls back to the public REST
    endpoint (no token needed) if `gh` is not on PATH, for a by-hand run.
    """
    if shutil.which("gh"):
        try:
            out = subprocess.run(
                ["gh", "pr", "list", "--repo", REPO, "--state", "open",
                 "--json", "number", "--jq", "length"],
                capture_output=True, text=True, timeout=20, check=True,
            ).stdout.strip()
            return int(out)
        except (subprocess.CalledProcessError, OSError, ValueError) as e:
            print(f"emit_machine_room_meters: gh pr list failed: {e}", file=sys.stderr)
            return None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/pulls?state=open&per_page=100",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return len(json.loads(r.read().decode()))
    except (OSError, ValueError) as e:
        print(f"emit_machine_room_meters: GitHub API fallback failed: {e}", file=sys.stderr)
        return None


def hours_with_rows(path):
    """Set of (date, hour) tuples with at least one row -- check_delivery.py's
    own hours_by_day(), flattened, since a streak needs to walk across day
    boundaries rather than look at one day's table cell.
    """
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("ts_utc") or "").strip()
            if not raw:
                continue
            try:
                ts = dt.datetime.fromisoformat(raw)
            except ValueError:
                continue
            if ts.tzinfo is not None:
                ts = ts.astimezone(dt.timezone.utc)
            seen.add((ts.date().isoformat(), ts.hour))
    return seen


def unbroken_hours():
    """Hours, counted backward from the most recent hour either collector
    actually reached, where BOTH data/basis.csv and data/p2p_basis.csv have
    at least one row -- stops at the first hour either collector missed.
    None if neither file has any rows yet (nothing to measure), never a
    guessed streak.

    Anchored to the data, not to wall-clock now: the chain collects on a
    30-minute cadence, so the current UTC hour routinely has no row yet for
    up to half an hour after it starts. Counting backward from
    datetime.now() would read that ordinary lag as a broken streak (0)
    every single hour until the next pass lands -- exactly the invented gap
    "gaps stay gaps" rules out. Starting from the latest hour either file
    actually has a row for measures whether collection has been unbroken up
    to the most recent thing it did, not whether it has already run again
    since the clock ticked over.
    """
    sets = [hours_with_rows(os.path.join(DATA, name)) for name in DELIVERY_FILES]
    if all(not s for s in sets):
        return None
    latest_date, latest_hour = max(key for s in sets for key in s)
    cursor = dt.datetime.fromisoformat(latest_date).replace(
        hour=latest_hour, tzinfo=dt.timezone.utc)
    streak = 0
    # A generous cap, not a real limit -- this is a sanity backstop against
    # an infinite loop if the clock or the data is somehow wrong, not a
    # plausible real streak length.
    for _ in range(24 * 365):
        key = (cursor.date().isoformat(), cursor.hour)
        if not all(key in s for s in sets):
            break
        streak += 1
        cursor -= dt.timedelta(hours=1)
    return streak


def main():
    doc = {
        "computed_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "collector_commits_today": collector_commits_today(),
        "open_pull_requests": open_pull_requests(),
        "unbroken_hours": unbroken_hours(),
    }

    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")

    print("emit_machine_room_meters: " + ", ".join(
        f"{k}={v}" for k, v in doc.items() if k != "computed_at"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
