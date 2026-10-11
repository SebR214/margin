#!/usr/bin/env python3
"""data/movers_week.json: the countries whose published figure changed most over the last 7 days.

Schema
    {
      "as_of_utc":  data/heatmap_daily.json's as_of_utc,
      "last_day":   the last day of the heatmap,
      "definition": the measure in words,
      "window_days": 7, "spark_days": 30,
      "days": the last 30 days (YYYY-MM-DD),
      "eligible": how many countries qualified,
      "top": [   the 8 largest absolute changes, rank 1 first (a page shows the first 4 or 5)
        {"rank", "ccy", "country",
         "change_pp":   now_pct - then_pct, in percentage points,
         "now_pct":     the figure published this hour (data/index_latest.json),
         "then_pct":    the figure published at the same hour 7 days earlier (data/index_hourly.csv),
         "now_hour_utc", "then_hour_utc",
         "spark": the last 30 daily values (null where no reading, never filled)}
      ]
    }
Measure (SEB-268, 11 Oct): the weekly change of a country is THIS HOUR's published figure minus the
figure published for the same hour of day 7 days earlier, both as published (data/index_hourly.csv
keeps every published figure; nothing is recomputed). A country with no figure this hour, or none
published at that hour a week ago, has no weekly change: a gap stays a gap. Only countries the
heatmap ranks (not "unmaintained" denominators) qualify. Sorted by absolute change, ties by code.
The same number is used on the home page and the countries page.
No wall clock; stdlib only.

Usage: python3 tools/emit_movers_week.py [--self-test]
"""

import csv
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

SRC = os.path.join(rc.DATA, "heatmap_daily.json")
OUT = os.path.join(rc.DATA, "movers_week.json")
HOURLY = os.path.join(rc.DATA, "index_hourly.csv")
LATEST = os.path.join(rc.DATA, "index_latest.json")
WINDOW, SPARK, TOP = 7, 30, 8
DEFINITION = (
    "This hour's published figure minus the figure published for the same hour 7 days earlier, in percentage "
    "points, both as published (data/index_hourly.csv). A country with no figure at either hour has no weekly "
    "change. Countries whose official rate is unmaintained are not ranked."
)


def _r(x):
    return None if x is None else round(x, 4)


def published():
    """{(ccy, hour 'YYYY-MM-DDTHH'): index_pct} exactly as published."""
    out = {}
    with open(HOURLY, newline="") as f:
        for r in csv.DictReader(f):
            try:
                out[(r["ccy"], r["hour_utc"][:13])] = float(r["index_pct"])
            except (KeyError, ValueError):
                continue
    return out


def seven_days_before(hour):
    return (dt.datetime.strptime(hour, "%Y-%m-%dT%H") - dt.timedelta(days=WINDOW)).strftime("%Y-%m-%dT%H")


def movers_from(latest_countries, pub, ranked_codes, cells_by_ccy):
    """Pure: the eligible movers, sorted. latest_countries: index_latest.json countries."""
    out = []
    for c in latest_countries:
        ccy = c["ccy"]
        if ccy not in ranked_codes or c.get("index_pct") is None or not c.get("hour_utc"):
            continue
        h_now = c["hour_utc"][:13]
        h_then = seven_days_before(h_now)
        then = pub.get((ccy, h_then))
        if then is None:
            continue
        now = c["index_pct"]
        out.append({"ccy": ccy, "country": c["country"], "change_pp": _r(now - then),
                    "now_pct": _r(now), "then_pct": _r(then),
                    "now_hour_utc": h_now + ":00:00Z", "then_hour_utc": h_then + ":00:00Z",
                    "spark": [_r(v) for v in cells_by_ccy.get(ccy, [])[-SPARK:]]})
    out.sort(key=lambda x: (-abs(x["change_pp"]), x["ccy"]))
    return out


def build():
    hm = json.load(open(SRC))
    latest = json.load(open(LATEST))
    ranked = {c["ccy"] for c in hm["currencies"] if c.get("ranked")}
    cells = {c["ccy"]: c["cells"] for c in hm["currencies"]}
    out = movers_from(latest["countries"], published(), ranked, cells)
    top = [{"rank": i, **t} for i, t in enumerate(out[:TOP], 1)]
    return {
        "as_of_utc": hm["as_of_utc"], "last_day": hm["last_day"], "definition": DEFINITION,
        "window_days": WINDOW, "spark_days": SPARK, "days": hm["days"][-SPARK:], "eligible": len(out), "top": top,
    }


def self_test(doc):
    rc.assert_no_nan(doc)
    t = doc["top"]
    assert len(t) == TOP, "need 8 movers"
    assert [x["rank"] for x in t] == list(range(1, TOP + 1))
    assert all(abs(a["change_pp"]) >= abs(b["change_pp"]) for a, b in zip(t, t[1:])), "sorted by size"
    for x in t:
        assert abs(x["change_pp"] - (x["now_pct"] - x["then_pct"])) < 0.001
        assert seven_days_before(x["now_hour_utc"][:13]) == x["then_hour_utc"][:13]
    # the known case: a country that fell from about 31 to 16 in three days must read as the week's change, not an average
    pub = {("IQD", "2026-10-04T08"): 31.0}
    mv = movers_from([{"ccy": "IQD", "country": "Iraq", "index_pct": 16.0, "hour_utc": "2026-10-11T08:00:00+00:00"}], pub, {"IQD"}, {})
    assert mv and mv[0]["change_pp"] == -15.0 and mv[0]["then_pct"] == 31.0 and mv[0]["now_pct"] == 16.0, mv
    # a gap stays a gap: nothing published 7 days earlier, no mover; an unranked country, no mover
    assert movers_from([{"ccy": "IQD", "country": "Iraq", "index_pct": 16.0, "hour_utc": "2026-10-11T08:00:00+00:00"}], {}, {"IQD"}, {}) == []
    assert movers_from([{"ccy": "IQD", "country": "Iraq", "index_pct": 16.0, "hour_utc": "2026-10-11T08:00:00+00:00"}], pub, set(), {}) == []
    print("movers_week self-test ok: %d eligible, top %s %+.1f" % (doc["eligible"], t[0]["ccy"], t[0]["change_pp"]))


def main():
    doc = build()
    self_test(doc)
    if "--self-test" in sys.argv:
        return
    rc.write_json(OUT, doc)


if __name__ == "__main__":
    main()
