#!/usr/bin/env python3
"""Luno USDT/ZAR order book, a second local-exchange source for South Africa (SEB-301, BACKLOG 17). Collected, NOT priced from.

Luno is a South African exchange with a public, unauthenticated USDTZAR book (api.luno.com/api/1/orderbook_top?pair=USDTZAR). One row a
run in data/zar_luno.csv, header in collector_venue_common.py. A failed pull is a row with source_ok false. Exits non-zero if nothing was
read. Under quarantine (data/source_registry.json): nothing reads it.

Usage:  python3 collector_zar_luno.py            # one pass, appends to data/zar_luno.csv
        python3 collector_zar_luno.py --selftest  # parser and guards on fixtures, no network
"""
import os
import sys

import collector_venue_common as cv

OUT = os.path.join(cv.HERE, "data", "zar_luno.csv")
URL = "https://api.luno.com/api/1/orderbook_top?pair=USDTZAR"
VENUE = "Luno ZAR"


def parse(payload):
    """Luno's {asks:[{price,volume}], bids:[...]} as (asks, bids) lists of (price, size). Malformed raises ValueError."""
    if not isinstance(payload, dict) or "asks" not in payload or "bids" not in payload:
        raise ValueError("no asks/bids in the answer")
    side = lambda xs: [(cv.num(x.get("price")), cv.num(x.get("volume"))) for x in xs if isinstance(x, dict)]
    return side(payload["asks"]), side(payload["bids"])


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
    return cv.finish("collector_zar_luno", [cv.book_row(cv.now_ts(), VENUE, "ZAR", asks, bids, err)], OUT)


def selftest():
    cv.selftest_common()
    asks, bids = parse({"asks": [{"price": "16.65", "volume": "700.00"}], "bids": [{"price": "16.60", "volume": "700.00"}]})
    assert asks == [(16.65, 700.0)] and bids == [(16.6, 700.0)], (asks, bids)
    row = cv.book_row("t", VENUE, "ZAR", asks, bids)
    assert row["source_ok"] and row["venue"] == "Luno ZAR" and row["ask_ref"] == 16.65, row
    for bad in ({}, [], {"asks": []}, "x"):
        try:
            parse(bad)
        except ValueError:
            continue
        raise AssertionError("malformed answer accepted: %r" % (bad,))
    print("collector_zar_luno self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
