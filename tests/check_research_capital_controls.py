#!/usr/bin/env python3
"""The capital-controls meter's stored files match a recomputation from the history files (SEB-301, Research page 1).

  1. the self-test of tools/research_capital_controls.py (the median, the 30-day floor, the year range, no official rate no row)
  2. recompute from data/history/ and compare every row with data/research/capital_controls.csv
  3. the CSV and the JSON hold the same rows, every row carries the label and a source, no field is empty
  4. an independent spot check of one currency-year straight from two source files: TWD 2023 from candles_bitopro_1d.csv against the
     official series the tool used (a single exchange series, so no median across venues is involved)

    python3 tests/check_research_capital_controls.py
"""
import csv
import json
import os
import statistics as st
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import research_capital_controls as rc  # noqa: E402


def main():
    assert subprocess.run([sys.executable, os.path.join(HERE, "tools", "research_capital_controls.py"), "--self-test"]).returncode == 0
    with open(rc.OUT_CSV, newline="") as f:
        stored = list(csv.DictReader(f))
    assert stored, "capital_controls.csv is empty"
    assert list(stored[0]) == rc.FIELDS, list(stored[0])
    for r in stored:
        assert all(v != "" for v in r.values()), r
        assert r["label"] == rc.LABEL and r["source"], r
        assert rc.FIRST_YEAR <= int(r["year"]) and int(r["days"]) >= rc.MIN_DAYS, r
    doc = json.load(open(rc.OUT_JSON))
    assert [dict((k, str(v)) for k, v in r.items()) for r in doc["rows"]] == stored, "the JSON and the CSV differ"
    rows, last = rc.compute()
    fresh = [dict((k, str(v)) for k, v in r.items()) for r in rows]
    assert fresh == stored, "stored rows differ from a recomputation (run tools/research_capital_controls.py)"
    assert doc["as_of_day"] == last
    # spot check straight from the files
    import backfill_history as bh
    data, _, _ = bh.history_data()
    off = data["off"]["TWD"]
    px = {}
    with open(os.path.join(HERE, "data", "history", "candles_bitopro_1d.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["ccy"] == "TWD" and r["ts_utc"][:4] == "2023" and "USDT" in r["pair"].upper():
                px[r["ts_utc"][:10]] = float(r["close"])
    prem = [(p / off[d] - 1) * 100 for d, p in px.items() if d in off and p > 0]
    mine = [r for r in stored if r["ccy"] == "TWD" and r["year"] == "2023"]
    assert mine and len(prem) >= rc.MIN_DAYS
    # the tool's street price for TWD may add other series; with only one venue the two agree to the rounding
    if int(mine[0]["series"]) == 1:
        assert abs(st.median(prem) - float(mine[0]["median_premium_pct"])) < 0.001, (st.median(prem), mine[0])
    else:
        assert abs(st.median(prem) - float(mine[0]["median_premium_pct"])) < 1.0, (st.median(prem), mine[0])
    print("capital controls test: ok (%d rows, %d currencies)" % (len(stored), len({r["ccy"] for r in stored})))


if __name__ == "__main__":
    main()
