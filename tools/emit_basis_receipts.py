#!/usr/bin/env python3
"""The receipt behind tape.html's street-price and bank-rate cells
(SEB-219): data/basis_receipts/<CCY>.json.

tape.html shows two raw numbers per country, both read straight off the
newest priced row in data/p2p_basis.csv -- the street price (`mid`, the
midpoint of that row's own buy/sell medians) and the bank rate
(`fx_mid_per_usd`). Neither is a computed index figure, so neither belongs
behind data/receipts/<CCY>.json: that file replays the premium-index
arithmetic (evidence vs. official rate vs. result_pct) emit_receipts.py
builds for countries.html's "how much more does a dollar cost here" number,
a different, unrelated quantity -- wiring tape.html's cells to it was tried
in an earlier pass of this issue and rejected on review because the receipt
that opened explained a different number than the one the reader clicked.

This writes the much smaller receipt tape.html's own numbers actually need:
one row per currency, the newest successfully-priced one, with nothing
decided or computed beyond what that single row already states.

Only `source_ok == "True"` binance_p2p rows with a positive `mid` count --
the same filter tape.html's own seedFromCsv() applies -- so a receipt never
exists for an hour tape.html itself would not have shown.

No wall clock: `computed_at` is the row's own `ts_utc`, so an unchanged
dataset regenerates byte-identical receipts, same as every other emitter
here. Stdlib only. Exits non-zero only if it cannot write.

Usage: python3 tools/emit_basis_receipts.py
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
P2P = os.path.join(DATA, "p2p_basis.csv")
OUT_DIR = os.path.join(DATA, "basis_receipts")


def num(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def latest_rows(path):
    """The newest source_ok binance_p2p row per currency, keyed by its own
    ts_utc so a later row always wins a tie. {} if the file is missing or
    empty -- never a guess.
    """
    if not os.path.exists(path):
        return {}
    latest = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("source") != "binance_p2p" or row.get("source_ok") != "True":
                continue
            mid = num(row.get("mid"))
            ccy = (row.get("ccy") or "").strip()
            ts = (row.get("ts_utc") or "").strip()
            if not mid or mid <= 0 or not ccy or not ts:
                continue
            cur = latest.get(ccy)
            if cur is None or ts >= cur["ts_utc"]:
                latest[ccy] = row
    return latest


def build_receipt(row):
    ccy = row["ccy"].strip()
    return {
        "ccy": ccy,
        "ts_utc": row["ts_utc"].strip(),
        "source": row.get("source"),
        "buy_median": num(row.get("buy_median")),
        "sell_median": num(row.get("sell_median")),
        "mid": num(row.get("mid")),
        "fx_mid_per_usd": num(row.get("fx_mid_per_usd")),
        "n_ads": int(num(row.get("n_ads")) or 0),
        "source_files": ["data/p2p_basis.csv"],
    }


def main():
    rows = latest_rows(P2P)
    receipts = {ccy: build_receipt(row) for ccy, row in rows.items()}

    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        for ccy, receipt in receipts.items():
            path = os.path.join(OUT_DIR, f"{ccy}.json")
            with open(path, "w") as f:
                json.dump(receipt, f, indent=2, sort_keys=True)
                f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write basis receipts: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  wrote {len(receipts)} basis receipts -> data/basis_receipts/")


if __name__ == "__main__":
    main()
