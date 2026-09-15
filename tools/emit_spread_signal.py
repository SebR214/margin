#!/usr/bin/env python3
"""A per-currency record of how wide the P2P buy/sell spread is running
against its OWN history -- a thin-market signal that already exists in every
two-sided reading (`data/p2p_basis.csv`'s `buy_median`/`sell_median`) and
costs nothing new to collect.

THE DECISION THIS FILE IMPLEMENTS (Linear SEB-52): the ad count (`n_ads`) is
clamped by the fetch ceiling and cannot tell a board of 10 ads from one of
500 (see SEB-50, `data/p2p_sides.csv`). The spread between the two sides is
not clamped, and SEB-49 showed it catching a real excursion in Algeria that
reverted within three hours while the official rate stayed flat and an
outside reference confirmed nothing real had moved.

`buy_median` is what a reader pays to acquire USDT; `sell_median` is what a
reader receives disposing of it. The ask normally sits above the bid, so
`(buy_median - sell_median)` is normally positive -- confirmed against the
live file: 86% of two-sided DZD readings have buy_median >= sell_median.

A single global threshold is not honest across currencies: NPR and BWP run
structurally wide (double-digit percent, every hour) and the same number on
a currency that normally runs near 2% is a real outlier. So every reading is
judged against ITS OWN currency's OWN prior history, never a fixed number.

CAUSAL BY CONSTRUCTION: a row's baseline is the mean of that currency's
spread readings STRICTLY BEFORE it, never a reading that came later. The CSV
is frozen at what was knowable at the time it was written -- the same
contract tools/emit_stress_signal.py uses for its own append-only rows -- so
a currency's baseline settling down over months never rewrites an old row's
ratio.

Needs MIN_HISTORY strictly-earlier two-sided readings of its own currency
before it will compute a baseline at all; short of that, the baseline and
ratio are None and stay a gap, not a guess.

Seven currencies (AOA, UAH, BND, XOF, INR, XAF, EGP, checked 2026-09-15) run
a mean spread at or below zero -- their board is typically crossed or flat,
not a real ask-over-bid cost. A ratio against a near-zero or negative
baseline blows up or flips sign for an ordinary move: EGP's baseline of
-0.05% turned a -0.40% reading, barely different from usual, into a ratio of
8 -- the largest number on the whole board, for nothing. So a ratio is only
computed when the baseline is a real positive cost (`> 0`); otherwise it
stays None, same as too little history.

THIS IS A RECORD, NOT A RULE: nothing here decides what a wide spread means
for a page a reader sees, or withholds or marks anything. That is SEB-52's
own last line -- a separate, Sebastian-gated decision.

Append-only and idempotent: a (ccy, ts_utc) pair already in the CSV is never
re-checked or rewritten. Stdlib only.

Usage: python3 tools/emit_spread_signal.py
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
BASIS = os.path.join(DATA, "p2p_basis.csv")
OUT_CSV = os.path.join(DATA, "p2p_spread_signal.csv")
OUT_JSON = os.path.join(DATA, "p2p_spread_signal_latest.json")

# Frozen from here on; anything new goes in a sidecar file, never a widened
# header.
FIELDS = ["ts_utc", "ccy", "spread_pct", "ccy_mean_spread_pct",
          "spread_ratio", "n_prior_readings"]

# A reading needs this many STRICTLY EARLIER two-sided readings of its own
# currency before its baseline means anything. Roughly a day and a quarter
# at the hourly cadence every currency here actually keeps.
MIN_HISTORY = 30


def num(v):
    try:
        x = float(str(v).strip())
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def two_sided(basis_rows):
    """Basis rows with a real, priceable pair of sides, oldest first. A row
    that failed (`source_ok=False`) or has only one side (the NGN fallback
    quote, a dead board) has no spread to speak of -- it is skipped, not
    treated as zero.
    """
    out = []
    for r in basis_rows:
        if (r.get("source_ok") or "").strip() != "True":
            continue
        buy, sell = num(r.get("buy_median")), num(r.get("sell_median"))
        mid = num(r.get("mid"))
        ts, ccy = (r.get("ts_utc") or "").strip(), (r.get("ccy") or "").strip()
        if buy is None or sell is None or not mid or not ts or not ccy:
            continue
        out.append({"ts_utc": ts, "ccy": ccy, "buy": buy, "sell": sell, "mid": mid})
    out.sort(key=lambda r: r["ts_utc"])
    return out


def compute(sided_rows):
    """One row per two-sided reading, each judged against its own currency's
    STRICTLY PRIOR readings only -- see the module docstring.
    """
    history = {}   # ccy -> [spread_pct, ...] seen so far, oldest first
    out = []
    for r in sided_rows:
        ccy = r["ccy"]
        spread_pct = round((r["buy"] - r["sell"]) / r["mid"] * 100, 4)
        prior = history.setdefault(ccy, [])
        if len(prior) >= MIN_HISTORY:
            baseline = sum(prior) / len(prior)
            ratio = round(spread_pct / baseline, 4) if baseline > 0 else None
        else:
            baseline = None
            ratio = None
        out.append({
            "ts_utc": r["ts_utc"],
            "ccy": ccy,
            "spread_pct": spread_pct,
            "ccy_mean_spread_pct": (round(baseline, 4)
                                     if baseline is not None else None),
            "spread_ratio": ratio,
            "n_prior_readings": len(prior),
        })
        prior.append(spread_pct)
    return out


def main():
    computed = compute(two_sided(rows(BASIS)))

    existing = rows(OUT_CSV)
    have = {(r["ccy"], r["ts_utc"]) for r in existing}
    fresh = [r for r in computed if (r["ccy"], r["ts_utc"]) not in have]

    new_file = not os.path.exists(OUT_CSV)
    if fresh or new_file:
        with open(OUT_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for r in fresh:
                w.writerow(r)
    print(f"  p2p_spread_signal.csv: {len(existing)} kept, {len(fresh)} appended")

    latest = {}
    for r in computed:
        latest[r["ccy"]] = r   # computed is oldest-first, so this ends on the newest
    ranked = sorted(
        (r for r in latest.values() if r["spread_ratio"] is not None),
        key=lambda r: r["spread_ratio"], reverse=True,
    )
    payload = {
        "min_history": MIN_HISTORY,
        "currencies": len(latest),
        "currencies_with_baseline": len(ranked),
        "latest": sorted(latest.values(), key=lambda r: r["ccy"]),
        "ranked_by_spread_ratio": ranked,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")
    print(f"  p2p_spread_signal_latest.json: {len(latest)} currencies, "
          f"{len(ranked)} with a baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
