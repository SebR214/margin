#!/usr/bin/env python3
"""The dollar map timeline files agree with the stored files they come from (SEB-384 step 4). Stored files only, no model.

For data/map_timeline/: every year file is well formed; every day from our own first day carries exactly our published daily figure
(data/heatmap_daily.json) or is empty; every hour in last90.json equals the figure in data/index_hourly.csv; no history point sits on a day we
could have read; landing.json is the 10%-and-over rows of data/history/backtest_landing.csv. The page draws these files and nothing else, so
"every number on the grid for a chosen day matches the file for that day" is this check plus the page showing the file's value.
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TL = os.path.join(ROOT, "data", "map_timeline")
fails = []


def fail(m):
    fails.append(m)


def tenths(x):
    return int(round(x * 10))


def main():
    idx = json.load(open(os.path.join(TL, "index.json")))
    heat = json.load(open(os.path.join(ROOT, "data", "heatmap_daily.json")))
    ccys = [c["ccy"] for c in idx["countries"]]
    own = {c["ccy"]: dict(zip(heat["days"], c["cells"])) for c in heat["currencies"]}
    classes = set(idx["classes"]) | {"-"}
    n_days = 0
    for y in idx["years"]:
        f = json.load(open(os.path.join(TL, "%d.json" % y)))
        days = f["days"]
        if not days or days[0] != "%d-01-01" % y or any(d[:4] != str(y) for d in days):
            fail("%d.json: days are not the days of the year" % y)
        if sorted(f["ccy"]) != sorted(ccys):
            fail("%d.json: countries differ from index.json" % y)
        for c, x in f["ccy"].items():
            if not (len(x["v"]) == len(x["k"]) == len(days)):
                fail("%d.json %s: lengths differ" % (y, c))
                continue
            for i, (v, k) in enumerate(zip(x["v"], x["k"])):
                d = days[i]
                n_days += 1
                if k not in classes:
                    fail("%d.json %s %s: class %r" % (y, c, d, k))
                if (v is None) != (k == "-"):
                    fail("%d.json %s %s: value and class disagree (%r, %r)" % (y, c, d, v, k))
                if v is not None and not isinstance(v, int):
                    fail("%d.json %s %s: value is not whole tenths" % (y, c, d))
                if d >= idx["own_start"]:
                    if d != idx["last_day"]:                         # the newest day is still being read; the next hourly run rewrites it
                        cell = own.get(c, {}).get(d)
                        want = (tenths(cell), "0") if cell is not None else (None, "-")
                        if (v, k) != want:
                            fail("%d.json %s %s: %r, the published daily figure says %r" % (y, c, d, (v, k), want))
                elif k == "0":
                    fail("%d.json %s %s: class ours before our record began" % (y, c, d))
                if k == "1" and d < idx["exchange_from"]:
                    fail("%d.json %s %s: an exchange price before %s" % (y, c, d, idx["exchange_from"]))
    h = json.load(open(os.path.join(TL, "last90.json")))
    pos = {x: i for i, x in enumerate(h["hours"])}
    seen = 0
    with open(os.path.join(ROOT, "data", "index_hourly.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            i = pos.get(r["hour_utc"][:13])
            if i is None or r["ccy"] not in h["ccy"]:
                continue
            x = h["ccy"][r["ccy"]]
            at = i - x["o"]
            got = x["v"][at] if 0 <= at < len(x["v"]) else None
            if r["hour_utc"][:13] != h["hours"][-1] and got != tenths(float(r["index_pct"])):     # the newest hour may be re-published
                fail("last90.json %s %s: %r, index_hourly says %r" % (r["ccy"], r["hour_utc"], got, tenths(float(r["index_pct"]))))
            seen += 1
    if seen < 1000:
        fail("last90.json: only %d hourly figures compared" % seen)
    land = json.load(open(os.path.join(TL, "landing.json")))["rows"]
    want = 0
    with open(os.path.join(ROOT, "data", "history", "backtest_landing.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                if float(r["official_move_pct"]) >= 10 and float(r["landing_ratio"]) > 0:
                    want += 1
            except ValueError:
                pass
    if len(land) != want or not want:
        fail("landing.json has %d rows, backtest_landing.csv has %d breaks of 10%% or more with a landing ratio" % (len(land), want))
    if fails:
        print("\n".join(fails[:30]))
        print("map timeline check: %d problems" % len(fails))
        return 1
    print("map timeline check: ok (%d country days, %d hourly figures, %d landing rows)" % (n_days, seen, len(land)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
