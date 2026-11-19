#!/usr/bin/env python3
"""SEB-468: after an official rate break, does the gap close or come back? Plain code, stored files only, no model.

Reads data/history/backtest_landing.csv (the breaks the replay found) and the exchange and official series the history files hold
(reported, not observed). For each break that has an exchange price series (street_series is not "none") it writes one row to
data/history/break_after.csv: the gap before the jump (as backtest_landing.csv has it) and the gap 30 and 90 days after.

Gap at a time: (typical exchange price in a week-wide window / typical official rate in the same window - 1) * 100. The window is the
7 days centred on day 30 (days 27 to 33 after the jump) or day 90 (days 87 to 93). "Typical" is the median of the days in the window.
The exchange price of a day is the one tools/backtest_watch.py uses (median of the exchange series of that day).
A window with no exchange price or no official rate, or one that runs past the last day we hold for that currency, is "none":
never filled, never carried over. Every row says "reported, not observed" and names its source. Nothing here feeds the index,
a price or the unbroken-hours count.

Usage:  python3 tools/break_after.py              # writes data/history/break_after.csv
        python3 tools/break_after.py --selftest   # rules on fixtures, writes nothing
"""
import csv
import datetime as dt
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
HIST = os.path.join(ROOT, "data", "history")
LANDING = os.path.join(HIST, "backtest_landing.csv")
OUT = os.path.join(HIST, "break_after.csv")
LABEL_HIST = "reported, not observed"
FIELDS = ["event_id", "ccy", "event_date", "gap_before_pct", "gap_30d_pct", "gap_90d_pct", "label", "source"]
SOURCE = "tools/break_after.py over backtest_landing.csv and data/history/ candles and official series"
HALF = 3     # a window is the day plus or minus this many days
NONE = "none"


def gap_at(street, off, day0, after_days):
    """The gap in percent, one decimal, in the window around day0 + after_days, or None.
    street {day: price}, off {day: official rate}. None when the window runs past either series or holds no price on a side."""
    centre = dt.date.fromisoformat(day0) + dt.timedelta(days=after_days)
    lo, hi = (centre - dt.timedelta(days=HALF)).isoformat(), (centre + dt.timedelta(days=HALF)).isoformat()
    if not street or not off or hi > max(street) or hi > max(off):
        return None
    s = [v for d, v in street.items() if lo <= d <= hi]
    o = [v for d, v in off.items() if lo <= d <= hi]
    if not s or not o:
        return None
    return round((st.median(s) / st.median(o) - 1) * 100, 1) + 0.0   # + 0.0: no "-0.0"


def build(landing_rows, street, off):
    """landing_rows: dicts of backtest_landing.csv. street {ccy: {day: price}}, off {ccy: {day: rate}}. One row per break with a street series."""
    out = []
    for r in landing_rows:
        if r["street_series"] in ("", NONE):
            continue
        c, d = r["ccy"], r["event_date"]
        row = {"event_id": r["event_id"], "ccy": c, "event_date": d,
               "gap_before_pct": r["premium_before_pct"] if r["premium_before_pct"] not in ("", NONE) else None,
               "gap_30d_pct": gap_at(street.get(c, {}), off.get(c, {}), d, 30),
               "gap_90d_pct": gap_at(street.get(c, {}), off.get(c, {}), d, 90),
               "label": LABEL_HIST, "source": SOURCE}
        out.append(row)
    return out


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (NONE if v is None else v) for k, v in r.items()})


def main():
    import backfill_history as bh
    import backtest_watch as bw
    data, _, _ = bh.history_data()
    street, _names = bw.street_by_day(data, bh)
    px = {c: {d: v[0] for d, v in per.items()} for c, per in street.items()}
    with open(LANDING, newline="") as f:
        land = list(csv.DictReader(f))
    rows = build(land, px, data["off"])
    write(OUT, rows)
    n30 = sum(1 for r in rows if r["gap_30d_pct"] is not None)
    n90 = sum(1 for r in rows if r["gap_90d_pct"] is not None)
    print("wrote %s: %d breaks with an exchange price series, %d with a gap at 30 days, %d at 90 days" % (os.path.relpath(OUT, ROOT), len(rows), n30, n90))
    return 0


def selftest():
    days = [(dt.date(2020, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(200)]
    off = {d: 10.0 for d in days}
    street = {d: 11.0 for d in days}                       # 10% above the official rate every day
    assert gap_at(street, off, "2020-01-01", 30) == 10.0
    street2 = dict(street)
    for d in days[27:34]:
        street2[d] = 12.0
    assert gap_at(street2, off, "2020-01-01", 30) == 20.0 and gap_at(street2, off, "2020-01-01", 90) == 10.0
    assert gap_at(street, off, "2020-01-01", 300) is None, "a window past the last day is a gap"
    assert gap_at(street, off, "2020-04-20", 90) is None, "a window past the last day is a gap"
    assert gap_at({}, off, "2020-01-01", 30) is None and gap_at(street, {}, "2020-01-01", 30) is None
    sparse = {d: 11.0 for d in days[:20]}
    sparse[days[199]] = 11.0
    assert gap_at(sparse, off, "2020-01-01", 30) is None, "no price inside the window is a gap, not a carry-over"
    land = [{"event_id": "A", "ccy": "XXX", "event_date": "2020-01-01", "premium_before_pct": "2.5", "street_series": "exch"},
            {"event_id": "B", "ccy": "XXX", "event_date": "2020-01-01", "premium_before_pct": "none", "street_series": "none"},
            {"event_id": "C", "ccy": "XXX", "event_date": "2020-06-01", "premium_before_pct": "none", "street_series": "exch"}]
    got = build(land, {"XXX": street}, {"XXX": off})
    assert [g["event_id"] for g in got] == ["A", "C"], "a break with no street series has no row"
    assert got[0]["gap_before_pct"] == "2.5" and got[0]["gap_30d_pct"] == 10.0 and got[0]["gap_90d_pct"] == 10.0
    assert got[1]["gap_before_pct"] is None and got[1]["gap_30d_pct"] == 10.0 and got[1]["gap_90d_pct"] is None
    assert all(g["label"] == LABEL_HIST and g["source"] for g in got)
    print("break_after self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
