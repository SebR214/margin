#!/usr/bin/env python3
"""The newest cash dollar per currency (SEB-422, step 3). No model.

Reads the daily table cash_rates (tools/daily_csv.py: collectors/template_tracker.py writes it) and writes data/cash_latest.json,
one entry per currency: the newest row with source_ok true, as the tracker gave it. A currency whose newest rows all failed has
no entry, so a page shows no cash line for it. Several trackers for one currency: the newest row wins, ties go to the tracker name
that sorts first. Nothing is averaged or filled in.

    python3 tools/emit_cash_latest.py
    python3 tools/emit_cash_latest.py --self-test
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import daily_csv  # noqa: E402

OUT = os.path.join(HERE, "data", "cash_latest.json")
NAME = "cash_rates"


def latest(rows):
    best = {}
    for r in rows:
        if str(r.get("source_ok")) != "True" or not r.get("mid"):
            continue
        key = (r["ts_utc"], "".join(chr(255 - ord(c)) for c in r["tracker"]))
        if r["ccy"] not in best or key > best[r["ccy"]][0]:
            best[r["ccy"]] = (key, r)
    out = {}
    for ccy, (_, r) in sorted(best.items()):
        out[ccy] = {"tracker": r["tracker"], "ts_utc": r["ts_utc"], "buy": float(r["buy"]) if r["buy"] else None,
                    "sell": float(r["sell"]) if r["sell"] else None, "mid": float(r["mid"])}
    return out


def main():
    rows = list(daily_csv.iter_dicts(NAME))
    if not rows:
        print("[error] no rows in the cash_rates table", file=sys.stderr)
        return 1
    doc = {"as_of_utc": max(r["ts_utc"] for r in rows), "rows": latest(rows)}
    if not doc["rows"]:
        print("[error] no cash_rates row with source_ok true", file=sys.stderr)
        return 1
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print("cash_latest.json: %d currencies" % len(doc["rows"]))
    return 0


def self_test():
    h = ["ts_utc", "tracker", "ccy", "buy", "sell", "mid", "updated_by_source", "source_ok", "error"]
    rows = [dict(zip(h, v)) for v in (
        ["2026-10-01T01:00:00Z", "a", "ARS", "1", "3", "2", "", "True", ""],
        ["2026-10-01T02:00:00Z", "a", "ARS", "", "", "", "", "False", "HTTPError"],
        ["2026-10-01T02:00:00Z", "b", "VES", "", "9", "9", "", "True", ""],
        ["2026-10-01T02:00:00Z", "c", "VES", "", "8", "8", "", "True", ""],
        ["2026-10-01T03:00:00Z", "d", "XXX", "", "", "", "", "False", "x"])]
    got = latest(rows)
    assert got["ARS"]["mid"] == 2.0 and got["ARS"]["ts_utc"] == "2026-10-01T01:00:00Z", "a failed newer row does not hide the good one"
    assert got["VES"]["tracker"] == "b" and got["VES"]["buy"] is None, got["VES"]
    assert "XXX" not in got, "a currency with only failed rows has no entry"
    with tempfile.TemporaryDirectory() as d:
        daily_csv.append_dicts(NAME, h, rows, data=d)
        assert len(list(daily_csv.iter_dicts(NAME, d))) == 5
    print("emit_cash_latest self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
