#!/usr/bin/env python3
"""KuCoin P2P, a fourth ad board for the currencies Binance has too few ads for (SEB-301, BACKLOG 17). Collected, NOT priced from.

KuCoin's public ad list (www.kucoin.com/_api/otc/ad/list, no login or key) is read for the ads that SELL USDT (side SELL), the first
page of 20. The price of an ad is 1 / fiatToCryptoPrice. One row per currency a run in data/p2p_kucoin.csv, header and the USD 500 rule
in collector_venue_common.py. A currency with no ads is a row with source_ok false and the count. Exits non-zero if no currency was
read. Under quarantine: nothing reads it.

Usage:  python3 collector_p2p_kucoin.py            # one pass, appends to data/p2p_kucoin.csv
        python3 collector_p2p_kucoin.py --selftest  # parser on fixtures, no network
"""
import os
import sys
import time

import collector_venue_common as cv

OUT = os.path.join(cv.HERE, "data", "p2p_kucoin.csv")
URL = "https://www.kucoin.com/_api/otc/ad/list"
VENUE = "KuCoin P2P"
CURRENCIES = ["AFN", "AOA", "BDT", "BND", "BWP", "ETB", "GHS", "MNT", "NPR", "SYP", "ZAR"]
GAP = 0.8


def parse(payload):
    """KuCoin's {success, items:[{fiatToCryptoPrice,limitMinQuote,limitMaxQuote}]} as [(price, min_fiat, max_fiat)]. Malformed raises ValueError."""
    if not isinstance(payload, dict) or not payload.get("success") or not isinstance(payload.get("items"), list):
        raise ValueError("not a KuCoin ad list")
    out = []
    for x in payload["items"]:
        if not isinstance(x, dict):
            continue
        f = cv.num(x.get("fiatToCryptoPrice"))
        out.append((1.0 / f if f else None, cv.num(x.get("limitMinQuote")), cv.num(x.get("limitMaxQuote"))))
    return out


def collect():
    import requests
    ts, rows = cv.now_ts(), []
    for i, c in enumerate(CURRENCIES):
        if i:
            time.sleep(GAP)
        ads = err = None
        try:
            r = requests.get(URL, params={"currency": "USDT", "legal": c, "side": "SELL", "page": 1, "pageSize": 20}, timeout=cv.TIMEOUT,
                             headers=cv.UA)
            r.raise_for_status()
            ads = parse(r.json())
        except Exception as e:
            ads = None
            err = "%s:%s" % (type(e).__name__, e)
        rows.append(cv.board_row(ts, VENUE, c, ads, err))
    return cv.finish("collector_p2p_kucoin", rows, OUT)


def selftest():
    cv.selftest_common()
    ads = parse({"success": True, "items": [{"fiatToCryptoPrice": "0.08", "limitMinQuote": "100", "limitMaxQuote": "50000"},
                                           {"fiatToCryptoPrice": "0", "limitMinQuote": "1", "limitMaxQuote": "2"}]})
    assert abs(ads[0][0] - 12.5) < 1e-9 and ads[1][0] is None, ads
    row = cv.board_row("t", VENUE, "GHS", ads)
    assert row["source_ok"] and row["n_board"] == 1 and row["n_ads"] == 1 and abs(row["ask_ref"] - 12.5) < 1e-6, row
    for bad in ({}, [], {"success": False, "items": []}, {"success": True, "items": None}, "x"):
        try:
            parse(bad)
        except ValueError:
            continue
        raise AssertionError("malformed answer accepted: %r" % (bad,))
    print("collector_p2p_kucoin self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
