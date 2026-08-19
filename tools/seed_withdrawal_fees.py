#!/usr/bin/env python3
"""Seed data/withdrawal_fees.csv from primary published sources.

The network leg of a corridor is the SENDING venue's USDT withdrawal fee. That
number is published per network and differs enormously between chains, so it is
a real cost decision rather than a constant -- which is what the route table on
the corridor page exists to show.

Run once to create the file. After that `tools/check_fees.py` re-reads the same
pages monthly and goes red on drift; this script is not the ongoing mechanism.

Sources, all public and read verbatim -- nothing here is derived or estimated:
  bitso            bitso.com/fees/transactions      (withdrawal table)
  independentreserve  independentreserve.com/fees   (crypto withdrawal table)
  coinbase         login-gated, NEVER scraped -> source_ok=False, fee empty

Parsers are imported from check_fees.py rather than duplicated, so the seed and
the monthly re-check can never disagree about how a page is read.
"""

import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

from check_fees import (  # noqa: E402
    BITSO_WITHDRAW_URL, COINBASE_URL, IR_WITHDRAW_URL, UA, WITHDRAWALS,
    WITHDRAWAL_FIELDS, fetch, flatten, parse_bitso_withdrawals,
    parse_ir_withdrawals,
)

try:
    import requests
except ImportError:
    requests = None

# Networks to record for Coinbase. NOT a guess at what Coinbase supports -- it
# is the set the counterpart venue (Bitso) accepts for USDT deposits, i.e. the
# only networks that could ever form a USD->MXN path. The fee itself stays
# empty because the schedule is behind a login and is never scraped.
COINBASE_NETWORKS = ["ethereum", "polygon", "tron", "solana"]


def rows(ts):
    out = []

    # --- Bitso: raw HTML, the withdrawal table is markup, not flattened text
    r = requests.get(BITSO_WITHDRAW_URL, timeout=20, headers=UA, allow_redirects=True)
    r.raise_for_status()
    for net, fee in sorted(parse_bitso_withdrawals(r.text).items()):
        out.append({"ts_utc": ts, "venue": "bitso", "asset": "USDT",
                    "network": net, "fee_asset_units": fee,
                    "source_url": r.url, "source_ok": True})

    # --- Independent Reserve: flattened text
    text, ir_url = fetch(IR_WITHDRAW_URL)
    for net, fee in sorted(parse_ir_withdrawals(text).items()):
        out.append({"ts_utc": ts, "venue": "independentreserve", "asset": "USDT",
                    "network": net, "fee_asset_units": fee,
                    "source_url": ir_url, "source_ok": True})

    # --- Coinbase: login-gated. Placeholder rows, no numbers, loud about it.
    for net in COINBASE_NETWORKS:
        out.append({"ts_utc": ts, "venue": "coinbase", "asset": "USDT",
                    "network": net, "fee_asset_units": "",
                    "source_url": COINBASE_URL, "source_ok": False})
    return out


def main():
    if requests is None:
        sys.exit("pip install requests")
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = rows(ts)

    os.makedirs(os.path.dirname(WITHDRAWALS), exist_ok=True)
    with open(WITHDRAWALS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WITHDRAWAL_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(data)

    ok = sum(1 for r in data if r["source_ok"])
    print(f"  wrote {os.path.relpath(WITHDRAWALS, HERE)} -- {len(data)} rows, "
          f"{ok} measured, {len(data) - ok} pending manual entry")
    for r in data:
        fee = r["fee_asset_units"]
        print(f"    {r['venue']:<19} {r['network']:<9} "
              f"{(str(fee) + ' USDT') if fee != '' else '— (login-gated)'}")


if __name__ == "__main__":
    main()
