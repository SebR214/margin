#!/usr/bin/env python3
"""Seed data/ramp_fees.csv -- the cited, dated record of each corridor's two
ramp legs: the bank fee to get the sender's money ONTO the on-ramp exchange
(deposit, in the sending currency) and the bank fee to get it OUT of the
off-ramp exchange to a bank account (withdrawal, in the receiving currency).

Until this shipped, the site said so explicitly (how-it-works.html: "the
bank fees to get money onto and off the exchanges... adding them is the next
data job"). This is that job.

Every venue here supports at least one LOCAL INSTANT (or same-day) bank rail
-- PayNow, a plain AUD bank transfer, InstaPay/PESONet, ACH, SPEI -- and each
one was checked against that specific venue's own published fee page rather
than assumed to cost a generic wire fee. The one exception is NZD->PHP's
deposit leg: Independent Reserve publishes no free NZD bank-transfer method
at all (only SWIFT at a NZD 50,000 minimum, or Australian-issued cards), so
that leg is recorded as a GAP, not a guessed number -- same as a withheld
country elsewhere on this site.

This is a SEED, not the live source of truth: the numbers themselves live in
collector.py's CORRIDORS dict (deposit/withdrawal sub-configs), with the same
citation comments, and decompose() reads them from there every hour. This
file is the auditable, dated record of what was checked and when -- same
role data/fee_tier_schedule.csv plays for the trading-fee tiers. Re-run with
--force to re-seed after a fee page changes; this script does not
periodically re-check on its own (unlike tools/check_fees.py's monthly
watch) -- a human re-reads the four pages and re-runs this.
"""

import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from collector import CORRIDORS  # noqa: E402

OUT = os.path.join(HERE, "data", "ramp_fees.csv")
FIELDS = [
    "ts_utc", "corridor", "leg", "venue", "method", "currency",
    "fee_type", "fee_value", "status", "source_url", "note",
]


def rows(ts):
    out = []
    for corridor, cfg in CORRIDORS.items():
        for leg in ("deposit", "withdrawal"):
            lc = cfg.get(leg)
            if not lc:
                continue
            status = "gap" if lc.get("fee_type") == "gap" else "measured"
            out.append({
                "ts_utc": ts, "corridor": corridor, "leg": leg,
                "venue": lc.get("venue"), "method": lc.get("method") or "",
                "currency": lc.get("fee_ccy"), "fee_type": lc.get("fee_type"),
                "fee_value": lc.get("fee_value") if lc.get("fee_value") is not None else "",
                "status": status, "source_url": lc.get("source_url"),
                "note": lc.get("note", ""),
            })
    return out


def main():
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = rows(ts)

    if os.path.exists(OUT) and os.path.getsize(OUT) > 0 and "--force" not in sys.argv:
        sys.exit(f"  {os.path.relpath(OUT, HERE)} already exists -- "
                 f"refusing to overwrite. Use --force to reseed.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(data)

    measured = sum(1 for r in data if r["status"] == "measured")
    print(f"  wrote {os.path.relpath(OUT, HERE)} -- {len(data)} rows, "
          f"{measured} measured, {len(data) - measured} gap")
    for r in data:
        fee = ("free" if r["fee_type"] == "free"
               else "GAP" if r["fee_type"] == "gap"
               else f"{r['fee_value']} {r['currency']}")
        print(f"    {r['corridor']:<10} {r['leg']:<11} {r['venue']:<19} "
              f"{r['method']:<14} {fee}")


if __name__ == "__main__":
    main()
