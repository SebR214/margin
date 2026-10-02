#!/usr/bin/env python3
"""The receipt behind how-it-was-built.html's three JSON-backed meters
(SEB-190, R2 for the meter row): data/meter_receipts/<meter>_<day>.json.

tools/emit_machine_room_meters.py (SEB-174/M2) already writes the three
numbers themselves to data/machine_room_meters.json. This re-runs the exact
same three measurements -- same git log invocation, same `gh pr list` call,
same two delivery CSVs -- but keeps the literal rows each number was counted
from, instead of collapsing straight to an integer, so js/receipt_replay.js's
click-to-reveal overlay can replay a meter the same way it already replays an
index number (SEB-173) or a corridor's cost (SEB-178).

Recomputed independently rather than imported from the machine_room_meters.json
this run already wrote: a receipt that merely echoed a cached integer would
have nothing to show a reader except the number again. The small chance this
run's own git log / gh pr list disagrees by one with the meters file written
moments earlier in the same pass (a PR merging mid-run, say) is the same
live-counting race every number on this site already carries; this receipt is
honest about what IT measured, not a promise that it reconciles to the exact
microsecond-old meters file.

Three receipts, one per meter tools/emit_machine_room_meters.py's own
docstring describes in full:

  commits_today    every commit on this checkout's current branch dated
                   today (UTC), each marked counted or excluded (a merged
                   pull request's "(#NNN)" subject), so the published count
                   can be checked by counting the counted ones.
  open_prs         the open pull requests `gh pr list` actually returned,
                   not just their number.
  unbroken_hours   the first and last hour of the streak, and whether each
                   of data/basis.csv and data/p2p_basis.csv had a row there.

Never fabricates a number it cannot compute: a step that fails leaves that
receipt unwritten and announces why on stderr, the same "gaps stay gaps" rule
as every collector here, applied to a receipt about a meter instead of a
price.

Stdlib only (gh, if present, is invoked as a subprocess; no library needs
it). Exits non-zero only if it cannot write.

Usage: python3 tools/emit_meter_receipts.py
"""

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.request

import emit_machine_room_meters as mroom  # noqa: E402 -- shared constants, not re-derived

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA = os.path.join(HERE, "data")
OUT_DIR = os.path.join(DATA, "meter_receipts")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today_utc():
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


# ------------------------------------------------------------- commits_today
def build_commits_receipt(day):
    """Every commit dated `day` (UTC) on this checkout's current branch, each
    marked counted (a collector pass) or excluded (a merged pull request) --
    the same git log tools/emit_machine_room_meters.py's own
    collector_commits_today() runs, kept in full instead of collapsed to a
    count. None if the command itself fails; never a guessed list.
    """
    cmd = ["git", "-C", HERE, "log", "--format=%cI%x1f%s", "-500"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"emit_meter_receipts: git log failed: {e}", file=sys.stderr)
        return None

    entries = []
    for line in out.strip("\n").split("\n"):
        if not line:
            continue
        iso, subject = line.split("\x1f", 1)
        try:
            when = dt.datetime.fromisoformat(iso)
        except ValueError:
            continue
        if when.astimezone(dt.timezone.utc).date().isoformat() != day:
            continue
        counted = not mroom.PR_SUFFIX_RE.search(subject)
        entries.append({
            "timestamp": iso,
            "subject": subject,
            "counted": counted,
            "excluded_reason": None if counted else "merged pull request",
        })

    return {
        "meter": "commits_today",
        "day": day,
        "computed_at": now_iso(),
        "value": sum(1 for e in entries if e["counted"]),
        "command": "git log --format=%cI%x1f%s -500 (this checkout, current branch)",
        "entries": entries,
        "source_files": ["https://github.com/" + mroom.REPO + "/commits/main"],
    }


# --------------------------------------------------------------- open_prs
def open_prs_receipt_data():
    """The open pull requests themselves, not just how many -- `gh pr list`,
    literally, same as tools/emit_machine_room_meters.py's own
    open_pull_requests(), falling back to the same unauthenticated REST
    endpoint when `gh` is not on PATH. None on failure; never a guessed list.
    """
    if shutil.which("gh"):
        cmd = ["gh", "pr", "list", "--repo", mroom.REPO, "--state", "open",
               "--json", "number,title,url,headRefName"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True).stdout
            prs = json.loads(out)
        except (subprocess.CalledProcessError, OSError, ValueError) as e:
            print(f"emit_meter_receipts: gh pr list failed: {e}", file=sys.stderr)
            return None
        command = "gh pr list --repo " + mroom.REPO + " --state open --json number,title,url,headRefName"
        rows = [{"number": p.get("number"), "title": p.get("title"), "url": p.get("url")} for p in prs]
        return rows, command
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{mroom.REPO}/pulls?state=open&per_page=100",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            prs = json.loads(r.read().decode())
    except (OSError, ValueError) as e:
        print(f"emit_meter_receipts: GitHub API fallback failed: {e}", file=sys.stderr)
        return None
    command = f"GET https://api.github.com/repos/{mroom.REPO}/pulls?state=open (gh not on PATH)"
    rows = [{"number": p.get("number"), "title": p.get("title"), "url": p.get("html_url")} for p in prs]
    return rows, command


def build_prs_receipt(day):
    data = open_prs_receipt_data()
    if data is None:
        return None
    rows, command = data
    return {
        "meter": "open_prs",
        "day": day,
        "computed_at": now_iso(),
        "value": len(rows),
        "command": command,
        "pull_requests": rows,
        "source_files": ["https://github.com/" + mroom.REPO + "/pulls?q=is%3Apr+is%3Aopen"],
    }


# --------------------------------------------------------- unbroken_hours
def build_hours_receipt(day):
    """The first and last hour of the unbroken streak
    tools/emit_machine_room_meters.py's own unbroken_hours() counts, and
    whether each of the two delivery files had a row there -- the same
    backward walk, kept at its boundaries instead of collapsed to a count.
    None if neither delivery file has any rows yet.
    """
    paths = [os.path.join(DATA, name) for name in mroom.DELIVERY_FILES]
    sets = [mroom.hours_with_rows(p) for p in paths]
    if all(not s for s in sets):
        return None

    anchor_date, anchor_hour = max(key for s in sets for key in s)
    cursor = dt.datetime.fromisoformat(anchor_date).replace(hour=anchor_hour, tzinfo=dt.timezone.utc)
    streak = 0
    last_in_streak = cursor
    for _ in range(24 * 365):
        key = (cursor.date().isoformat(), cursor.hour)
        if not all(key in s for s in sets):
            break
        last_in_streak = cursor
        streak += 1
        cursor -= dt.timedelta(hours=1)

    def boundary(moment):
        key = (moment.date().isoformat(), moment.hour)
        return {
            "date": key[0],
            "hour": key[1],
            **{name: (key in s) for name, s in zip(mroom.DELIVERY_FILES, sets)},
        }

    return {
        "meter": "unbroken_hours",
        "day": day,
        "computed_at": now_iso(),
        "value": streak,
        "streak_end": boundary(dt.datetime.fromisoformat(anchor_date).replace(hour=anchor_hour, tzinfo=dt.timezone.utc)),
        "streak_start": boundary(last_in_streak),
        "source_files": ["data/" + name for name in mroom.DELIVERY_FILES],
    }


def main():
    day = today_utc()
    receipts = {
        "commits_today": build_commits_receipt(day),
        "open_prs": build_prs_receipt(day),
        "unbroken_hours": build_hours_receipt(day),
    }

    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        written = 0
        for meter, receipt in receipts.items():
            if receipt is None:
                continue
            path = os.path.join(OUT_DIR, f"{meter}_{day}.json")
            with open(path, "w") as f:
                json.dump(receipt, f, indent=2, sort_keys=True)
                f.write("\n")
            written += 1
    except OSError as e:
        print(f"  [error] cannot write meter receipts: {e}", file=sys.stderr)
        sys.exit(1)

    skipped = [m for m, r in receipts.items() if r is None]
    print(f"  wrote {written} of {len(receipts)} meter receipts -> data/meter_receipts/"
          + (f" (skipped: {', '.join(skipped)})" if skipped else ""))


if __name__ == "__main__":
    main()
