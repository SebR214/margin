#!/usr/bin/env python3
"""Every commission, in one file. Builds data/requests_latest.json.

A commission is a GitHub issue labelled `commission` (see ROADMAP.md,
"Commission" and `tools/serve_common.py:request_series`). This never talks to
a CSV -- GitHub's issue tracker is the record of record for a commission's
status, the same way an exchange's own API is the record of record for a fee.

Status is read from the issue's own labels, never guessed:

  open      the issue is still open
  rejected  closed, and `wontfix` is on it -- a probe failed and said why
  accepted  closed, and `wontfix` is not on it -- closed by a merged PR

`commission` stays on an issue for its whole life (see agents/COMMISSION.md),
so this is the one label this file relies on to find every one of them, past
and present.

Stdlib only -- shells out to `gh`, the same way tools/serve_common.py already
does to file a commission in the first place.

Usage: python3 tools/emit_requests.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "requests_latest.json")
REPO = "SebR214/margin"


def fetch_issues():
    """Every issue ever labelled `commission`, open or closed. Raises on any
    transport or auth failure -- a commission list this tool cannot trust is
    not one it should write over the last good one silently."""
    out = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", "commission",
         "--state", "all", "--limit", "1000",
         "--json", "number,title,state,labels,createdAt,closedAt"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


def status_of(issue):
    """open / accepted / rejected, from the issue's own state and labels."""
    if issue.get("state") == "OPEN":
        return "open"
    names = {l.get("name") for l in (issue.get("labels") or [])}
    return "rejected" if "wontfix" in names else "accepted"


def build_requests(issues):
    rows = []
    for issue in issues:
        n = issue.get("number")
        rows.append({
            "number": n,
            "title": issue.get("title") or "",
            "state": (issue.get("state") or "").lower(),
            "status": status_of(issue),
            "created_at": issue.get("createdAt"),
            "closed_at": issue.get("closedAt"),
            "url": f"https://github.com/{REPO}/issues/{n}",
        })
    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return rows


def as_of(rows):
    """Newest event across every request -- never the wall clock, so a run
    that finds nothing new writes a byte-identical file."""
    stamps = [s for r in rows for s in (r["created_at"], r["closed_at"]) if s]
    return max(stamps) if stamps else None


def write(rows):
    payload = {
        "as_of_utc": as_of(rows),
        "counts": {
            "open": sum(1 for r in rows if r["status"] == "open"),
            "accepted": sum(1 for r in rows if r["status"] == "accepted"),
            "rejected": sum(1 for r in rows if r["status"] == "rejected"),
        },
        "requests": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return payload


def main():
    try:
        issues = fetch_issues()
    except Exception as e:
        print(f"  [error] could not read commission issues: {e}", file=sys.stderr)
        sys.exit(1)

    rows = build_requests(issues)
    payload = write(rows)
    c = payload["counts"]
    print(f"  {len(rows)} commissions -- {c['open']} open, "
          f"{c['accepted']} accepted, {c['rejected']} rejected "
          f"-> {os.path.relpath(OUT, HERE)}")


if __name__ == "__main__":
    main()
