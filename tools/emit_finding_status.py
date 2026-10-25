#!/usr/bin/env python3
"""data/finding_status.json: each finding's retest status, once it has 14 days of retest rows (SEB-301, BACKLOG 13).

Reads data/finding_tests.csv (tools/retest_findings.py appends a row per finding per day). A finding appears here only when it has
rows on at least 14 different days; 'invalid' rows (a test that could not run fairly) never count. No prose, only ids, dates and
numbers: the pages put the words ("Still holds", "Weaker", "No longer true") from copy.json.

    {"as_of_utc": ..., "min_days": 14,
     "findings": {"<id>": {"status": holds | weaker | no_longer_true (the newest row), "days": n, "first_tested": date,
                           "last_rechecked": date}}}

Nothing published by tools/emit_findings.py or any index figure changes. Usage:  python3 tools/emit_finding_status.py [--self-test]
"""
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTS = os.path.join(ROOT, "data", "finding_tests.csv")
OUT = os.path.join(ROOT, "data", "finding_status.json")
MIN_DAYS = 14
STATUSES = ("holds", "weaker", "no_longer_true")


def retest_status(rows, fid):
    """The status to show for one finding, or None. rows are data/finding_tests.csv as dicts."""
    mine = sorted((r for r in rows if r.get("finding_id") == fid and r.get("status") in STATUSES), key=lambda r: r["ts_utc"])
    days = sorted({r["ts_utc"][:10] for r in mine})
    if len(days) < MIN_DAYS:
        return None
    return {"status": mine[-1]["status"], "days": len(days), "first_tested": days[0], "last_rechecked": days[-1]}


def build(rows):
    out = {}
    for fid in sorted({r.get("finding_id") for r in rows if r.get("finding_id")}):
        s = retest_status(rows, fid)
        if s:
            out[fid] = s
    stamp = max((r["ts_utc"] for r in rows), default="")
    return {"as_of_utc": stamp, "min_days": MIN_DAYS, "findings": out}


def read_rows(path=TESTS):
    if not os.path.exists(path):
        sys.exit("emit_finding_status: %s is missing" % path)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    if "--self-test" in sys.argv:
        d0 = dt.date(2026, 10, 1)
        rows = [{"ts_utc": "%sT03:00:00+00:00" % (d0 + dt.timedelta(days=i)), "finding_id": "a", "status": "holds"} for i in range(14)]
        assert build(rows)["findings"]["a"]["days"] == 14 and build(rows[:13])["findings"] == {}
        print("emit_finding_status self-test: ok")
        return 0
    doc = build(read_rows())
    with open(OUT, "w") as f:                             # persistence before display
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    print("emit_finding_status: %d of the findings have 14 days of retests" % len(doc["findings"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
