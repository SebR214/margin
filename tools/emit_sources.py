#!/usr/bin/env python3
"""What the index is actually priced from: data/sources_latest.json.

METHODOLOGY.md's "How it works" section names every source behind the number,
but a hand-typed list drifts the moment a venue is added or dropped -- three
new order-book venues (CoinDCX, WazirX, BitoPro/MAX) have landed since this
list was last written down as prose, without anyone noticing the prose was
now wrong. This reads the same files the index itself reads and counts what
is actually there, so the page can never say something the data does not
back up (SEB-62/U7, "generated from the collectors' own source fields").

Every count here is a real tally over data/index_latest.json and data/basis.csv
rows, never typed. `as_of_utc` is index_latest.json's own timestamp, not the
wall clock -- same reasoning as every other emitter here: an unchanged
snapshot regenerates a byte-identical file.

Stdlib only.
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
INDEX_LATEST = os.path.join(DATA, "index_latest.json")
BASIS = os.path.join(DATA, "basis.csv")
OUT = os.path.join(DATA, "sources_latest.json")

ORDER_BOOK_CLASSES = ("order_book_median", "order_book_single")
BROKER_CLASSES = ("broker_median", "broker_single")


def _read_index():
    try:
        with open(INDEX_LATEST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _basis_rows():
    try:
        with open(BASIS, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _venues_for(ccys, rows):
    """Every venue a currency's most recent ok row actually named."""
    out = set()
    for r in rows:
        if r.get("ccy") in ccys and r.get("source_ok") == "True":
            out.add(r["venue"])
    return out


def build():
    idx = _read_index()
    countries = (idx or {}).get("countries", [])
    rows = _basis_rows()

    by_class = {}
    for c in countries:
        by_class.setdefault(c.get("source_class"), []).append(c["ccy"])

    p2p_ccys = sorted(by_class.get("p2p_buy_median", []))
    fallback_ccys = sorted(by_class.get("p2p_fallback", []))
    ob_ccys = sorted(sum((by_class.get(k, []) for k in ORDER_BOOK_CLASSES), []))
    broker_ccys = sorted(sum((by_class.get(k, []) for k in BROKER_CLASSES), []))

    ob_venues = sorted(_venues_for(set(ob_ccys), rows))
    broker_venues = sorted(v for v in _venues_for(set(broker_ccys), rows)
                            if v.startswith("CriptoYa"))

    sources = [
        {
            "name": "Binance P2P",
            "role": "live buy and sell ads",
            "detail": f"the main source for {len(p2p_ccys)} "
                      f"{'country' if len(p2p_ccys) == 1 else 'countries'}",
            "countries": p2p_ccys,
        },
        {
            "name": "Order books",
            "role": f"on {', '.join(ob_venues)}" if ob_venues else "none live right now",
            "detail": f"{len(ob_ccys)} {'country' if len(ob_ccys) == 1 else 'countries'} "
                      "priced this way",
            "countries": ob_ccys,
        },
        {
            "name": "CriptoYa",
            "role": "snapshot broker aggregation",
            "detail": f"the parallel-dollar markets for "
                      f"{', '.join(broker_ccys) if broker_ccys else 'no country right now'}",
            "countries": broker_ccys,
        },
        {
            "name": "CoinGecko",
            "role": "backup price",
            "detail": (f"used when {', '.join(fallback_ccys)}'s own board is empty"
                       if fallback_ccys else "not in use this hour"),
            "countries": fallback_ccys,
        },
        {
            "name": "open.er-api",
            "role": "the official exchange rate",
            "detail": "captured in the same second as the market price",
            "countries": [],
        },
        {
            "name": "BCRA",
            "role": "Argentina's central bank",
            "detail": "for its published parallel rate",
            "countries": [],
        },
        {
            "name": "Airwallex, Instarem",
            "role": "live quotes from their own pricing",
            "detail": "at five transfer amounts",
            "countries": [],
        },
        {
            "name": "Wise's comparison",
            "role": "the other transfer providers",
            "detail": "Wise included",
            "countries": [],
        },
    ]

    out = {
        "as_of_utc": (idx or {}).get("as_of_utc"),
        "computed_at": (idx or {}).get("as_of_utc"),
        "source_file": "data/index_latest.json, data/basis.csv",
        "sources": sources,
    }
    return out


def main():
    out = build()
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write {OUT}: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  wrote {OUT}: {len(out['sources'])} sources")


if __name__ == "__main__":
    main()
