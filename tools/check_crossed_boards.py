#!/usr/bin/env python3
"""Crossed boards (SEB-302, index v1.5): each rule is proved with a bad row through the real emitter.

    python3 tools/check_crossed_boards.py          # unit cases, then four rows through tools/emit_countries.py
    python3 tools/check_crossed_boards.py --unit   # unit cases only, no data needed

The integration case copies the stored data and adds, for one person-to-person country (the newest hour plus one), a Binance row and
sometimes an OKX row, runs the real emitter on the copy and reads the country's file:
  A  Binance crossed by 2%, OKX 1% above Binance          -> priced from the median of the two buy medians, marked crossed_boards_agree
  B  the same, OKX 6% above Binance                       -> withheld, with the crossed reason
  C  Binance crossed by 0.05% (a near tie), no OKX        -> priced from Binance alone, not marked
  D  Binance crossed by 2%, OKX with only 4 ads           -> withheld
"""
import csv
import datetime as dt
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import emit_countries as ec  # noqa: E402


def unit():
    assert not ec.crossed(100.0, 100.0) and not ec.crossed(101.0, 100.0)            # a tie and a normal board
    assert not ec.crossed(99.96, 100.0)                                              # 0.04% of the mid: a near tie
    assert ec.crossed(99.8, 100.0)                                                   # 0.2%: crossed
    assert ec.crossed(962.36, 1119.67)                                               # Angola as stored
    assert not ec.crossed(None, 100.0) and not ec.crossed(100.0, None)
    ec.V15 = False
    assert ec.crossed(99.96, 100.0), "with the v1.4 rule any crossing counts"
    ec.V15 = True
    refused = {"source_ok": "False", "error": ec.CROSSED_TEXT + ", so the two are not the same market (buy 1, sell 2)", "buy_median": "1", "sell_median": "2"}
    assert ec.board_row_usable(refused) and ec.board_row_usable({"source_ok": "True"})
    assert not ec.board_row_usable(dict(refused, error="guard: buy price 5 is 40 times the official rate 1, outside 0.5 to 30"))
    assert not ec.board_row_usable(dict(refused, sell_median=""))
    okx = {"UGX": {dt.datetime(2026, 10, 14, 3): [{"buy_median": "102.9"}]}}
    assert ec.boards_agree("UGX", dt.datetime(2026, 10, 14, 3), 100.0, okx, {})
    assert not ec.boards_agree("UGX", dt.datetime(2026, 10, 14, 3), 99.0, {"UGX": {}}, {})
    assert not ec.boards_agree("UGX", dt.datetime(2026, 10, 14, 3), 90.0, okx, {})   # 14% apart
    print("crossed boards, unit cases: ok")


def scenario(ccy, kind):
    work = tempfile.mkdtemp(prefix="crossed-")
    for d in ("tools", "agents"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(work, d), ignore=shutil.ignore_patterns("* [0-9]*", "__pycache__"))
    shutil.copytree(os.path.join(ROOT, "data"), os.path.join(work, "data"), ignore=shutil.ignore_patterns("* [0-9].*"))
    p = os.path.join(work, "data", "p2p_basis.csv")
    raw = open(p, newline="").read().split("\n")
    hdr = next(csv.reader([raw[0]]))
    last = None
    for ln in raw[1:]:
        if ln.strip():
            r = dict(zip(hdr, next(csv.reader([ln.rstrip("\r")]))))
            if r["ccy"] == ccy and r["source_ok"] == "True":
                last = r
    t = dt.datetime.fromisoformat(last["ts_utc"]) + dt.timedelta(hours=1)
    buy = float(last["buy_median"])
    gap = 0.0005 if kind == "C" else 0.02
    row = dict(last, ts_utc=t.isoformat(), buy_median=str(buy), sell_median=str(buy * (1 + gap)), mid=str(buy * (1 + gap / 2)), n_ads="20",
               source_ok="False", error=ec.CROSSED_TEXT + ", so the two are not the same market (buy %s, sell %s)" % (buy, buy * (1 + gap)))
    fmt = lambda rr, h: ",".join('"%s"' % rr[k] if "," in rr[k] else rr[k] for k in h)
    with open(p, "a", newline="") as f:
        f.write("\n".join([""] if not raw[-1] == "" else []) + fmt(row, hdr) + "\n")
    if kind != "C":
        po = os.path.join(work, "data", "p2p_okx.csv")
        oraw = open(po, newline="").read().split("\n")
        ohdr = next(csv.reader([oraw[0]]))
        olast = None
        for ln in oraw[1:]:
            if ln.strip():
                r = dict(zip(ohdr, next(csv.reader([ln.rstrip("\r")]))))
                if r["ccy"] == ccy and r["source_ok"] == "True":
                    olast = r
        ob = buy * (1.06 if kind == "B" else 1.01)
        orow = dict(olast, ts_utc=(t + dt.timedelta(minutes=1)).isoformat(), buy_median=str(ob), sell_median=str(ob * 0.99), mid=str(ob),
                    n_ads="4" if kind == "D" else "20", source_ok="True", error="")
        with open(po, "a", newline="") as f:
            f.write("\n".join([""] if not oraw[-1] == "" else []) + fmt(orow, ohdr) + "\n")
    r = subprocess.run([sys.executable, "tools/emit_countries.py"], cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    return json.load(open(os.path.join(work, "data", "countries", ccy + ".json"))), buy


def integration():
    idx = json.load(open(os.path.join(ROOT, "data", "index_latest.json")))
    ccy = None
    for c in idx["countries"]:
        d = json.load(open(os.path.join(ROOT, "data", "countries", c["ccy"] + ".json")))
        if d.get("source_class") == "p2p_buy_median" and d.get("n_boards") == 2 and c["ccy"] not in ("UAH", "XAF", "XOF"):
            ccy = c["ccy"]
            break
    assert ccy, "no two-board person-to-person country to test with"
    a, buy = scenario(ccy, "A")
    assert a.get("index_pct") is not None and a.get("n_boards") == 2 and a.get("crossed_boards_agree", {}).get("crossed") == ["binance_p2p"], a.get("no_value_reason")
    assert abs(a["buy_price"] - statistics.median([buy, buy * 1.01])) < 1e-6 * buy, a["buy_price"]
    assert "round_trip_pct" not in a
    b, _ = scenario(ccy, "B")
    assert b.get("index_pct") is None and (b.get("no_value_reason") or "").startswith(ec.CROSSED_TEXT), b
    c, _ = scenario(ccy, "C")
    assert c.get("index_pct") is not None and c.get("n_boards") == 1 and abs(c["buy_price"] - buy) < 1e-9 and "crossed_boards_agree" not in c, c.get("no_value_reason")
    d, _ = scenario(ccy, "D")
    assert d.get("index_pct") is None and (d.get("no_value_reason") or "").startswith(ec.CROSSED_TEXT), d
    print("crossed boards, four bad rows through the real emitter (%s): A priced from both boards and marked, B (OKX 6%% away) withheld, "
          "C (near tie) priced from Binance, D (OKX thin) withheld: ok" % ccy)


if __name__ == "__main__":
    unit()
    if "--unit" not in sys.argv:
        integration()
