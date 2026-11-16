#!/usr/bin/env python3
"""SEB-464: collector_p2p_okx_sides on fixtures only. No live data."""
import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import collector_p2p_okx_sides as c

FX = {"AOA": 900.0, "BWP": 13.0, "GHS": 11.0, "LBP": 89500.0, "ZAR": 16.0}
TS = "2026-01-01T00:00:00+00:00"


def ad(price, lo="1", hi="999999999"):
    return {"price": str(price), "quoteMinAmountPerOrder": lo, "quoteMaxAmountPerOrder": hi}


def make_get(n_sell_side, n_buy_side, fail=(), unsupported=()):
    def get(url):
        ccy = url.split("quoteCurrency=")[1].split("&")[0].upper()
        side = "sell" if "side=sell" in url else "buy"
        if ccy in fail:
            raise RuntimeError("down")
        if ccy in unsupported:
            return {"code": c.UNSUPPORTED_CODE, "data": {}}
        n = n_sell_side if side == "sell" else n_buy_side
        ads = [ad(100 + i) for i in range(n)]
        ads.append(ad(1, lo="9999999999", hi="99999999999"))  # too big a minimum: not counted
        return {"code": 0, "data": {side: ads}}
    return get


def main():
    rows, n_ok = c.build_rows(TS, c.CURRENCIES, FX, get=make_get(12, 3))
    assert n_ok == 5 and len(rows) == 5
    for r in rows:
        assert r["source_ok"] is True and r["n_buy_ads"] == 12 and r["n_sell_ads"] == 3, r
        assert r["buy_median"] == 104.5, r  # median of the first 10 asks, 100..109

    rows, n_ok = c.build_rows(TS, c.CURRENCIES, FX, get=make_get(0, 0))
    assert n_ok == 5 and all(r["n_buy_ads"] == 0 and r["buy_median"] == "" for r in rows)

    rows, n_ok = c.build_rows(TS, c.CURRENCIES, FX, get=make_get(5, 5, fail=("GHS",), unsupported=("LBP",)))
    bad = {r["ccy"]: r for r in rows if not r["source_ok"]}
    assert n_ok == 3 and set(bad) == {"GHS", "LBP"}
    assert all(r["error"] and r["n_buy_ads"] == "" for r in bad.values())

    rows, n_ok = c.build_rows(TS, ["ZAR"], {}, get=make_get(5, 5))
    assert n_ok == 0 and rows[0]["source_ok"] is False and "no FX mid" in rows[0]["error"]

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x", "p2p_okx_sides.csv")
        good, _ = c.build_rows(TS, c.CURRENCIES, FX, get=make_get(12, 3))
        c.append(good, p)
        c.append(good, p)
        with open(p, newline="") as f:
            got = list(csv.DictReader(f))
        assert len(got) == 10 and list(got[0]) == c.FIELDS
    print("agent_p2p_okx_sides: ok")


if __name__ == "__main__":
    main()
