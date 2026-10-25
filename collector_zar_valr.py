#!/usr/bin/env python3
"""VALR USDT/ZAR order book, a first local-exchange source for South Africa (SEB-301, BACKLOG 17). Collected, NOT priced from.

South Africa has no price on the map because Binance has too few ads. VALR is a South African exchange with a public, unauthenticated
USDTZAR book (api.valr.com/v1/public/USDTZAR/orderbook). One row a run in data/zar_valr.csv, header in collector_venue_common.py. A failed
pull is a row with source_ok false. Exits non-zero if nothing was read. Under quarantine (data/source_registry.json): nothing reads it.

Usage:  python3 collector_zar_valr.py            # one pass, appends to data/zar_valr.csv
        python3 collector_zar_valr.py --selftest  # parser and guards on fixtures, no network
"""
import os
import sys

import collector_venue_common as cv

OUT = os.path.join(cv.HERE, "data", "zar_valr.csv")
URL = "https://api.valr.com/v1/public/USDTZAR/orderbook"
VENUE = "VALR"


def parse(payload):
    """VALR's {Asks:[{price,quantity}], Bids:[...]} as (asks, bids) lists of (price, size). Malformed raises ValueError."""
    if not isinstance(payload, dict) or "Asks" not in payload or "Bids" not in payload:
        raise ValueError("no Asks/Bids in the answer")
    side = lambda xs: [(cv.num(x.get("price")), cv.num(x.get("quantity"))) for x in xs if isinstance(x, dict)]
    return side(payload["Asks"]), side(payload["Bids"])


def collect():
    import requests
    asks = bids = err = None
    try:
        r = requests.get(URL, timeout=cv.TIMEOUT, headers=cv.UA)
        r.raise_for_status()
        asks, bids = parse(r.json())
    except Exception as e:
        asks = bids = None
        err = "%s:%s" % (type(e).__name__, e)
    return cv.finish("collector_zar_valr", [cv.book_row(cv.now_ts(), VENUE, "ZAR", asks, bids, err)], OUT)


def selftest():
    cv.selftest_common()
    asks, bids = parse({"Asks": [{"price": "16.63", "quantity": "600"}], "Bids": [{"price": "16.60", "quantity": "600"}, {"price": "0", "quantity": "5"}]})
    assert asks == [(16.63, 600.0)] and bids == [(16.6, 600.0), (None, 5.0)], (asks, bids)
    row = cv.book_row("t", VENUE, "ZAR", asks, bids)
    assert row["source_ok"] and row["venue"] == "VALR" and row["ask_ref"] == 16.63 and row["bid_ref"] == 16.6, row
    for bad in ({}, [], {"Asks": []}, "x"):
        try:
            parse(bad)
        except ValueError:
            continue
        raise AssertionError("malformed answer accepted: %r" % (bad,))
    print("collector_zar_valr self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
