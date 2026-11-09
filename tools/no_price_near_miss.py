#!/usr/bin/env python3
"""How close is each country with no price to having one? (BACKLOG 27a, SEB-301.)

Reads the no_price list of data/gap_report.json and the ad threshold the price rule uses (emit_countries.MIN_BUY_ADS). From
data/p2p_sides.csv it takes the sell-ad count of each UTC hour (the newest row of the hour) over the newest 7 days, and writes
data/no_price_near_miss.json: per currency the median ad count, the threshold, the hours counted, the hours at or above the
threshold, and a status: 'no data' (no rows), 'near miss' (median at least half the threshold) or 'far'.
Stored rows only; nothing is filled in. Usage:
    python3 tools/no_price_near_miss.py
    python3 tools/no_price_near_miss.py --self-test
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emit_countries  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
WINDOW_DAYS = 7


def hourly_counts(rows, ccy, since_hour):
    """{hour: sell ads} for one currency, newest row of an hour wins, only hours from since_hour on."""
    out = {}
    for r in sorted((r for r in rows if r.get("ccy") == ccy), key=lambda r: r["ts_utc"]):
        try:
            n = int(float(r["n_sell"]))
        except (KeyError, TypeError, ValueError):
            continue
        h = r["ts_utc"][:13]
        if h >= since_hour:
            out[h] = n
    return out


def judge(counts, threshold):
    """One currency's entry from its hourly counts."""
    if not counts:
        return {"status": "no data", "median_ads": None, "threshold": threshold, "hours": 0, "hours_at_or_above": 0}
    vals = list(counts.values())
    med = statistics.median(vals)
    return {"status": "near miss" if med >= threshold / 2 else "far", "median_ads": med, "threshold": threshold,
            "hours": len(vals), "hours_at_or_above": sum(1 for v in vals if v >= threshold)}


def build(no_price, rows, threshold, newest_ts):
    since = (dt.datetime.fromisoformat(newest_ts) - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H")
    return {"as_of_utc": newest_ts, "window_days": WINDOW_DAYS, "threshold": threshold,
            "currencies": {c: judge(hourly_counts(rows, c, since), threshold) for c in sorted(no_price)}}


def self_test():
    rows = [{"ts_utc": "2026-01-01T0%d:00:00+00:00" % i, "ccy": "XXX", "n_sell": str(n)} for i, n in enumerate((3, 8, 10, 12))]
    doc = build(["XXX", "YYY"], rows, 10, "2026-01-01T04:00:00+00:00")
    x = doc["currencies"]["XXX"]
    assert x["median_ads"] == 9 and x["hours_at_or_above"] == 2 and x["status"] == "near miss", x
    assert doc["currencies"]["YYY"]["status"] == "no data"
    print("self-test ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    with open(os.path.join(DATA, "gap_report.json")) as f:
        no_price = [e["ccy"] for e in json.load(f)["no_price"]]
    with open(os.path.join(DATA, "p2p_sides.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("data/p2p_sides.csv has no rows", file=sys.stderr)
        return 1
    doc = build(no_price, rows, emit_countries.MIN_BUY_ADS, max(r["ts_utc"] for r in rows))
    with open(os.path.join(DATA, "no_price_near_miss.json"), "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    near = sorted(c for c, v in doc["currencies"].items() if v["status"] == "near miss")
    print("wrote data/no_price_near_miss.json: %d currencies, near miss: %s" % (len(no_price), ", ".join(near) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
