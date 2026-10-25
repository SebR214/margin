#!/usr/bin/env python3
"""BACKLOG 20a: tools/diagnose_disagree.py labels a flagged Binance/OKX disagreement, and its output on the real CSVs is finite numbers.

  fake pair XXX, Binance sell 100 and OKX sell 120 for 10 hours, 20 ads each  -> 'one side moves alone', sell side, gap 20.0
  the same pair with OKX at 4 ads                                             -> 'one side thin'
  a pair with 5 hours of rows                                                 -> 'not enough evidence'
  the real CSVs                                                               -> every number in the JSON is a finite float

    python3 tests/agent_diagnose_disagree.py
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import diagnose_disagree as dd  # noqa: E402


def finite_numbers(x, path=""):
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return
    if isinstance(x, (int, float)):
        assert math.isfinite(x), "not finite: %s = %r" % (path, x)
    elif isinstance(x, dict):
        for k, v in x.items():
            finite_numbers(v, path + "/" + str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            finite_numbers(v, "%s[%d]" % (path, i))


def main():
    a = dd.rows_for(dd.A, 10, 100, 100, 20)
    d = dd.diagnose(a, dd.rows_for(dd.B, 10, 100, 120, 20))
    assert d["label"] == "one side moves alone" and d["gap_side"] == "sell" and d["median_gap_pct"]["sell"] == 20.0, d
    assert dd.diagnose(a, dd.rows_for(dd.B, 10, 100, 120, 4))["label"] == "one side thin"
    assert dd.diagnose(dd.rows_for(dd.A, 5, 100, 100, 20), dd.rows_for(dd.B, 5, 100, 120, 20))["label"] == "not enough evidence"
    assert subprocess.run([sys.executable, os.path.join(HERE, "tools", "diagnose_disagree.py"), "--self-test"]).returncode == 0
    r = subprocess.run([sys.executable, os.path.join(HERE, "tools", "diagnose_disagree.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = json.load(open(os.path.join(HERE, "data", "disagree_diagnosis.json")))
    assert doc["markets"], "no flagged market diagnosed"
    finite_numbers(doc)
    for c, m in doc["markets"].items():
        assert m["label"] in ("not enough evidence", "one side thin", "one side moves alone", "unexplained"), (c, m["label"])
    print("diagnose_disagree test: ok (%d markets)" % len(doc["markets"]))


if __name__ == "__main__":
    main()
