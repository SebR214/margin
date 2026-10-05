#!/usr/bin/env python3
"""data/movers_week.json: the currencies that moved most this week against their own record.

Schema
    {
      "as_of_utc":  data/heatmap_daily.json's as_of_utc,
      "last_day":   the last day of the heatmap,
      "definition": the measure in words,
      "window_days": 7, "min_earlier_days": 14, "min_recent_days": 4, "spark_days": 30,
      "days": the last 30 days (YYYY-MM-DD), the x axis of every `spark`,
      "eligible": how many currencies qualified,
      "top": [   the 8 largest absolute moves, rank 1 first (a page shows the first 4)
        {"rank", "ccy", "country",
         "change_pp":       recent_median_pct - earlier_median_pct, in percentage points,
         "recent_median_pct", "earlier_median_pct",
         "recent_days": days with a value among the last 7, "earlier_days": days with a value before them,
         "recent_values": the last 7 daily values (null where no reading),
         "spark": the last 30 daily values (null where no reading, never filled)}
      ]
    }
Measure: for a currency, a day's value is the daily gap in data/heatmap_daily.json
(median of that day's readings, percent above the official rate). recent = the last 7
days of the heatmap, earlier = every day before them. change_pp = median of recent
values minus median of earlier values. Only currencies the heatmap ranks (not
"unmaintained" denominators), with at least 14 earlier days and 4 recent days with a
value, qualify. Sorted by absolute change, ties by currency code.
Stored file only (data/heatmap_daily.json); no wall clock; stdlib only.

Usage: python3 tools/emit_movers_week.py [--self-test]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

SRC = os.path.join(rc.DATA, "heatmap_daily.json")
OUT = os.path.join(rc.DATA, "movers_week.json")
WINDOW, MIN_EARLIER, MIN_RECENT, SPARK, TOP = 7, 14, 4, 30, 8
DEFINITION = (
    "Last-7-day median of the daily gap minus the median of all earlier days, in percentage points, "
    "from data/heatmap_daily.json. Needs at least 14 earlier days and 4 of the last 7 days with a "
    "value. Currencies whose official rate is unmaintained are not ranked. Days with no reading are "
    "null and left out of the medians."
)


def _r(x):
    return None if x is None else round(x, 4)


def build():
    hm = json.load(open(SRC))
    days = hm["days"]
    out = []
    for c in hm["currencies"]:
        if not c.get("ranked"):
            continue
        cells = c["cells"]
        recent = cells[-WINDOW:]
        earlier = [v for v in cells[:-WINDOW] if v is not None]
        rv = [v for v in recent if v is not None]
        if len(earlier) < MIN_EARLIER or len(rv) < MIN_RECENT:
            continue
        rm, em = rc.median(rv), rc.median(earlier)
        out.append({"ccy": c["ccy"], "country": c["country"], "change_pp": _r(rm - em),
                    "recent_median_pct": _r(rm), "earlier_median_pct": _r(em),
                    "recent_days": len(rv), "earlier_days": len(earlier),
                    "recent_values": [_r(v) for v in recent], "spark": [_r(v) for v in cells[-SPARK:]]})
    out.sort(key=lambda x: (-abs(x["change_pp"]), x["ccy"]))
    top = [{"rank": i, **t} for i, t in enumerate(out[:TOP], 1)]
    return {
        "as_of_utc": hm["as_of_utc"], "last_day": hm["last_day"], "definition": DEFINITION,
        "window_days": WINDOW, "min_earlier_days": MIN_EARLIER, "min_recent_days": MIN_RECENT,
        "spark_days": SPARK, "days": days[-SPARK:], "eligible": len(out), "top": top,
    }


def self_test(doc):
    rc.assert_no_nan(doc)
    t = doc["top"]
    assert len(t) == TOP, "need 8 movers"
    assert [x["rank"] for x in t] == list(range(1, TOP + 1))
    assert all(abs(a["change_pp"]) >= abs(b["change_pp"]) for a, b in zip(t, t[1:])), "sorted by size"
    for x in t:
        assert len(x["spark"]) == len(doc["days"]) == SPARK
        assert len(x["recent_values"]) == WINDOW
        assert x["earlier_days"] >= MIN_EARLIER and x["recent_days"] >= MIN_RECENT
        assert abs(x["change_pp"] - (x["recent_median_pct"] - x["earlier_median_pct"])) < 0.001
    print("movers_week self-test ok: %d eligible, top %s" % (doc["eligible"], t[0]["ccy"]))


def main():
    doc = build()
    self_test(doc)
    if "--self-test" in sys.argv:
        return
    rc.write_json(OUT, doc)


if __name__ == "__main__":
    main()
