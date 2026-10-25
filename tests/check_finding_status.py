#!/usr/bin/env python3
"""A finding's retest status shows only after 14 days of retest rows (SEB-301, BACKLOG 13).

Feeds tools/emit_finding_status.retest_status rows shaped like data/finding_tests.csv and checks:
  13 days of rows            -> nothing (None)
  14 days of rows            -> the newest row's status, 14 days, first and last dates
  two rows on one day        -> one day, not two
  'invalid' rows             -> never count as a day, never the status
  the status moves           -> the latest status shows, not the first
  another finding's rows     -> ignored
and that on the stored data no finding shows a status before it has 14 days.

    python3 tests/check_finding_status.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import emit_finding_status as ef  # noqa: E402


def rows(fid, n, status="holds", start="2026-10-01"):
    d0 = dt.date.fromisoformat(start)
    return [{"ts_utc": "%sT03:00:00+00:00" % (d0 + dt.timedelta(days=i)), "finding_id": fid, "status": status} for i in range(n)]


def main():
    assert ef.retest_status(rows("a", 13), "a") is None, "13 days must show nothing"
    assert ef.retest_status([], "a") is None
    got = ef.retest_status(rows("a", 14), "a")
    assert got == {"status": "holds", "days": 14, "first_tested": "2026-10-01", "last_rechecked": "2026-10-14"}, got
    dup = rows("a", 13) + [dict(r, ts_utc=r["ts_utc"].replace("T03", "T15")) for r in rows("a", 13)]
    assert ef.retest_status(dup, "a") is None, "two rows on one day are one day"
    inv = rows("a", 13) + rows("a", 5, "invalid", "2026-10-14")
    assert ef.retest_status(inv, "a") is None, "invalid rows never count"
    moved = rows("a", 13) + rows("a", 1, "weaker", "2026-10-14")
    assert ef.retest_status(moved, "a")["status"] == "weaker", "the newest status shows"
    last_invalid = rows("a", 14) + rows("a", 1, "invalid", "2026-10-15")
    got = ef.retest_status(last_invalid, "a")
    assert got["status"] == "holds" and got["last_rechecked"] == "2026-10-14", got
    mixed = rows("a", 14) + rows("b", 20, "no_longer_true")
    assert ef.retest_status(mixed, "a")["status"] == "holds" and ef.retest_status(mixed, "b")["status"] == "no_longer_true"
    stored = ef.read_rows()
    for fid in {r["finding_id"] for r in stored}:
        days = {r["ts_utc"][:10] for r in stored if r["finding_id"] == fid and r["status"] in ef.STATUSES}
        shown = ef.retest_status(stored, fid)
        assert (shown is None) == (len(days) < 14), (fid, len(days), shown)
    doc = ef.build(stored)
    assert all(v["days"] >= 14 for v in doc["findings"].values()) and doc["min_days"] == 14
    assert doc["findings"] == {f: ef.retest_status(stored, f) for f in doc["findings"]}
    print("finding status test: ok")


if __name__ == "__main__":
    main()
