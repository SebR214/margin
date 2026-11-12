#!/usr/bin/env python3
"""Daily gap history for flagged source pairs (BACKLOG 28a, SEB-301).

Takes each pair with flag true in the disagree list of data/gap_report.json, reuses tools/emit_source_pairs.py's hourly
prices per source (basis.csv, p2p_basis.csv, p2p_okx.csv) and groups the hours both sides priced into UTC days. Writes
data/pair_gap_daily.csv with one row per currency, pair and day: the median gap in percent and the hours compared. An
hour missing from either side is skipped, never counted as zero. Usage:
    python3 tools/pair_gap_daily.py
    python3 tools/pair_gap_daily.py --self-test
"""
import collections
import csv
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emit_source_pairs as esp  # noqa: E402

DATA = os.path.join(os.path.dirname(HERE), "data")
OUT = os.path.join(DATA, "pair_gap_daily.csv")
FIELDS = ["ccy", "a", "b", "day", "median_gap_pct", "hours"]


def daily_gaps(price_a, price_b):
    """{day: (median_gap_pct, hours)} for the hours both {hour: price} series share."""
    by_day = collections.defaultdict(list)
    for h in sorted(set(price_a) & set(price_b)):
        gap = abs(price_a[h] - price_b[h]) / min(price_a[h], price_b[h]) * 100.0
        by_day[h[:10]].append(gap)
    return {day: (round(statistics.median(gaps), 2), len(gaps)) for day, gaps in by_day.items()}


def build(pairs, series):
    """series: {ccy: {source: {hour: price}}}."""
    rows = []
    for p in pairs:
        if not p.get("flag"):
            continue
        src = series.get(p["ccy"], {})
        for day, (median_gap, hours) in sorted(daily_gaps(src.get(p["a"], {}), src.get(p["b"], {})).items()):
            rows.append({"ccy": p["ccy"], "a": p["a"], "b": p["b"], "day": day, "median_gap_pct": median_gap, "hours": hours})
    return rows


def self_test():
    a = {"2026-10-01T%02d" % h: 100.0 for h in range(3)}
    a.update({"2026-10-02T%02d" % h: 100.0 for h in range(2)})
    b = {"2026-10-01T%02d" % h: 110.0 for h in range(3)}
    b.update({"2026-10-02T%02d" % h: 120.0 for h in range(2)})
    b["2026-10-02T05"] = 999.0                       # an hour a has no price for: must be skipped, not zero
    g = daily_gaps(a, b)
    assert g["2026-10-01"] == (10.0, 3), g
    assert g["2026-10-02"] == (20.0, 2), g
    rows = build([{"ccy": "XXX", "a": "s1", "b": "s2", "flag": True}], {"XXX": {"s1": a, "s2": b}})
    assert len(rows) == 2 and rows[0]["day"] == "2026-10-01" and rows[0]["median_gap_pct"] == 10.0, rows
    assert build([{"ccy": "XXX", "a": "s1", "b": "s2", "flag": False}], {"XXX": {"s1": a, "s2": b}}) == []
    print("pair_gap_daily self-test: ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    with open(os.path.join(DATA, "gap_report.json")) as f:
        pairs = json.load(f)["disagree"]
    basis, binance, okx = esp.read("basis.csv"), esp.read("p2p_basis.csv"), esp.read("p2p_okx.csv")
    if not binance:
        print("data/p2p_basis.csv has no rows", file=sys.stderr)
        return 1
    since = min(r["ts_utc"] for r in binance)[:13]
    rows = build(pairs, esp.prices_by_source(basis, binance, okx, since))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("wrote data/pair_gap_daily.csv: %d flagged pair(s), %d row(s)" % (
        sum(1 for p in pairs if p.get("flag")), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
