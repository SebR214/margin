#!/usr/bin/env python3
"""Research page 1: the dollar premium as a capital-controls meter (SEB-301).

For each currency and each year 2018 to the newest, the median daily premium of the street price against the official rate:

    premium of a day = street price / official rate - 1, in percent

The street price of a day is tools/backtest_watch.street_by_day: the median of every exchange series the history files hold that
day (venues turned over when 1/price sits nearer the official rate), plus the Argentina blue mid. The official rate is the BIS daily
series, or fawazahmed0 and Frankfurter v2 where BIS has none (tools/backfill_history.history_data). Only days with both count. A
currency-year with fewer than MIN_DAYS such days is left out, never filled. "managed" is the currency's latest managed_flag in
data/fx_rates.csv (the same split as tools/backtest_watch.py).

All of it is history: reported by exchanges and statistical offices, not observed by us, never in the index, a price or the
unbroken-hours count. Output:

    data/research/capital_controls.csv    ccy,type,year,median_premium_pct,days,series,first_day,last_day,partial,label,source
    data/research/capital_controls.json   the same rows plus the method numbers the page prints

Usage:  python3 tools/research_capital_controls.py             # compute and write both files
        python3 tools/research_capital_controls.py --self-test  # the arithmetic on fixtures, writes nothing
"""
import csv
import datetime as dt
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
OUT_DIR = os.path.join(ROOT, "data", "research")
OUT_CSV = os.path.join(OUT_DIR, "capital_controls.csv")
OUT_JSON = os.path.join(OUT_DIR, "capital_controls.json")
FIRST_YEAR = 2018
MIN_DAYS = 30
LABEL = "reported, not observed"
SOURCE = "tools/research_capital_controls.py over data/history/ candles, parallel dollar and official series"
FIELDS = ["ccy", "type", "year", "median_premium_pct", "days", "series", "first_day", "last_day", "partial", "label", "source"]


def yearly(street, off, managed, first_year=FIRST_YEAR, min_days=MIN_DAYS):
    """Rows from {ccy: {day: (street price, [series names])}} and {ccy: {day: official rate}}. Pure."""
    last = max(d for per in street.values() for d in per)
    rows = []
    for c in sorted(street):
        o = off.get(c, {})
        per_year = {}
        for day, (p, who) in street[c].items():
            y = int(day[:4])
            if y < first_year or day not in o or not o[day] or p <= 0:
                continue
            per_year.setdefault(y, []).append((day, (p / o[day] - 1) * 100, who))
        for y in sorted(per_year):
            pts = per_year[y]
            if len(pts) < min_days:
                continue
            days = sorted(d for d, _, _ in pts)
            rows.append({"ccy": c, "type": "managed" if c in managed else "floating", "year": y,
                         "median_premium_pct": round(st.median(p for _, p, _ in pts), 3), "days": len(pts),
                         "series": len({v for _, _, who in pts for v in who}), "first_day": days[0], "last_day": days[-1],
                         "partial": "yes" if days[-1] < "%d-12-25" % y else "no", "label": LABEL, "source": SOURCE})
    return rows, last


def compute():
    import backfill_history as bh
    import backtest_watch as bw
    data, _, _ = bh.history_data()
    street, _ = bw.street_by_day(data, bh)
    rows, last = yearly(street, data["off"], data["managed"])
    if not rows:
        sys.exit("research_capital_controls: no currency-year had enough days")
    return rows, last


def document(rows, last):
    return {"as_of_day": last, "first_year": FIRST_YEAR, "min_days": MIN_DAYS, "label": LABEL, "source": SOURCE,
            "years": sorted({r["year"] for r in rows}), "countries": len({r["ccy"] for r in rows}), "rows": rows}


def write(rows, last, csv_path=OUT_CSV, json_path=OUT_JSON):
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with open(json_path, "w") as f:
        json.dump(document(rows, last), f, separators=(",", ":"))
        f.write("\n")


def selftest():
    def days(y, n, price, who=("A",)):
        d0 = dt.date(y, 1, 1)
        return {str(d0 + dt.timedelta(days=i)): (price, list(who)) for i in range(n)}
    street = {"AAA": days(2019, 40, 1.10), "BBB": dict(days(2020, 40, 3.0, ("A", "B")), **days(2021, 10, 3.0)), "OLD": days(2016, 60, 2.0)}
    off = {"AAA": {d: 1.0 for d in street["AAA"]}, "BBB": {d: 2.0 for d in street["BBB"]}, "OLD": {d: 1.0 for d in street["OLD"]}}
    rows, last = yearly(street, off, {"BBB"})
    assert [(r["ccy"], r["year"]) for r in rows] == [("AAA", 2019), ("BBB", 2020)], rows            # OLD before 2018, BBB 2021 too short
    a, b = rows
    assert a["median_premium_pct"] == 10.0 and a["days"] == 40 and a["type"] == "floating" and a["series"] == 1, a
    assert b["median_premium_pct"] == 50.0 and b["type"] == "managed" and b["series"] == 2 and b["partial"] == "yes", b
    odd = {"AAA": {"2019-01-%02d" % i: (p, ["A"]) for i, p in enumerate([1.0, 1.2, 9.0], 1)}}
    r2, _ = yearly(odd, {"AAA": {d: 1.0 for d in odd["AAA"]}}, set(), min_days=3)
    assert r2[0]["median_premium_pct"] == 20.0, "the median, not the mean"
    gap, _ = yearly({"AAA": days(2019, 40, 1.1)}, {"AAA": {}}, set())
    assert gap == [], "no official rate, no row"
    doc = document(rows, last)
    assert doc["years"] == [2019, 2020] and doc["countries"] == 2
    print("research_capital_controls self-test: ok")
    return 0


def main():
    if "--self-test" in sys.argv:
        return selftest()
    rows, last = compute()
    write(rows, last)                                  # persistence before display
    yrs = sorted({r["year"] for r in rows})
    print("research_capital_controls: %d currency-years, %d currencies, %d to %d, through %s" % (
        len(rows), len({r["ccy"] for r in rows}), yrs[0], yrs[-1], last))
    return 0


if __name__ == "__main__":
    sys.exit(main())
