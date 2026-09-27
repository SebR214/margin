#!/usr/bin/env python3
"""How much money the street can actually take, per country, per hour.

The standard objection to this site's country premium: "sure, the street
price is +90% in Algeria, but on what volume?" This answers it, from data
the site already collects.

What exists to answer it with, and what does not:

  - data/p2p_offers.csv (SEB-56) holds the individual ad prices behind every
    P2P buy-side and sell-side median, in the order Binance's own search
    returned them -- which is board order, best price first. It does NOT
    hold each ad's own size.
  - data/basis.csv (the order-book layer -- IndependentReserve, Coins.ph)
    holds one bid/ask tick per venue per hour, no order-book walk at all.
    There is no size data behind it whatsoever, so no depth figure can be
    computed for a country priced from that layer, and this script does not
    invent one. Gaps stay gaps, same rule as everywhere else in this repo.

So the only lever available is collector_p2p.py's own search filter:
`FILTER_USD` (mirrored below, not imported, for the same
import-independence reason every collector here duplicates its own small
constants -- see collector_p2p.py's `captured_this_hour` docstring). Every
ad the collector fetches was matched to the search "can this ad fill an
order worth about USD 500", which is a real, if approximate, floor on that
ad's own size. Walking the fetched ads in board order and counting how many
hold before the price moves is therefore a genuine lower bound on the
market's depth near the current price, built entirely from the guarantee
already baked into how those ads were fetched -- nothing new is asked of
the source.

THE THRESHOLD, AND WHY (read this before changing it):

  "Meaningful price move" is defined as the point where an ad's price is
  more than THRESHOLD_PCT away from the best ad on that side, same board,
  same hour. THRESHOLD_PCT = 1.0 (one percent). Chosen for three reasons,
  each tied to a number this repo already publishes:

  1. It is on the unit this site already reports in (basis_bps / index_pct
     are percentages of the same kind), so a reader who understands "this
     country's premium is +12%" is reading the same scale here.
  2. It is small next to what this index exists to measure. Countries on
     this site routinely show premiums in the tens or hundreds of percent
     (METHODOLOGY's own sanity band runs to +200%) -- so 1% is nowhere near
     "this counts as the premium moving", it is the first sign of the board
     thinning out, caught early on purpose.
  3. It is comfortably above the ad-to-ad noise on a real, calibrated
     board. Surveyed on 2026-09-27: the Philippines' own top 10 buy ads
     spanned 62.40 to 62.68 PHP, a 0.45% range -- below THRESHOLD_PCT, so a
     liquid market's own quoting noise does not trip this at ad 2. Algeria's
     top 10 spanned 255.20 to 258.00, a 1.1% range, entirely inside the
     first page -- so a genuinely thin, mispriced board DOES trip it, inside
     the very evidence (MIN_BUY_ADS = 10 ads) the published price already
     rests on.

  This is deliberately NOT a per-country threshold (e.g. some fraction of
  that country's own round_trip_pct). A per-country number would need its
  own justification and would make two countries' depth figures not
  directly comparable to each other -- exactly the property a reader
  scanning several country pages needs. One fixed, small, published number,
  applied identically everywhere, is the simpler and more honest choice.

THE FLOOR, AND WHY IT STAYS A FLOOR:

  Only ROWS ads (10, mirroring collector_p2p.py) are ever fetched per side
  per hour. data/p2p_depth.csv separately records the REAL total ad count
  behind the search (often much larger -- the Philippines showed 115 buy
  ads live on 2026-09-27 against a 10-ad page). That total is read here for
  context only. It is never used to extend depth_usd past what the fetched
  page actually priced: a 105-ad tail this script has never seen could hold
  the same price as the page, or could crack immediately after it -- both
  are guesses, and this script does not publish one. When the fetched page
  never breaches THRESHOLD_PCT, the honest answer is "at least $X, not sure
  how much further" (is_floor=True), never a number invented past it.

Derived, never authoritative, same contract as tools/emit_countries.py and
tools/emit_latest.py: no wall clock, computed straight from
data/p2p_offers.csv and data/p2p_depth.csv, so an unchanged dataset
regenerates a byte-identical file and a currency with no buy-side ads this
hour produces an ABSENT entry, never a fabricated zero.

Usage: python3 tools/emit_depth.py
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OFFERS = os.path.join(DATA, "p2p_offers.csv")
DEPTH_COUNTS = os.path.join(DATA, "p2p_depth.csv")
OUT = os.path.join(DATA, "street_depth_latest.json")

# Mirrors collector_p2p.py's FILTER_USD / ROWS. Duplicated, not imported --
# see this file's own docstring and collector_p2p.py's `captured_this_hour`
# docstring for why every collector/emitter here keeps its own copy of the
# handful of constants it needs rather than reaching across files.
FILTER_USD = 500
ROWS = 10

# See the docstring above, "THE THRESHOLD, AND WHY", for the full reasoning.
THRESHOLD_PCT = 1.0


# ------------------------------------------------------------- parsing
def rows(path):
    """Every readable row of a CSV. Unreadable or missing file -> no rows."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _f(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------- computation
def latest_offer_board(offer_rows):
    """{ccy: {"ts_utc": str, "buy": [prices, board order]}} -- newest hour only.

    Board order is preserved exactly as read from the CSV (which preserves
    exactly the order collector_p2p.py wrote, itself the order Binance's
    search returned): best price first. Only the buy side is used -- the
    published index price (`p2p_buy_median`, tools/emit_countries.py) is
    built from the buy side, and this is the depth behind that same figure,
    not a second, different measurement.
    """
    newest_ts = {}
    for r in offer_rows:
        ccy, ts = r.get("ccy"), r.get("ts_utc")
        if not ccy or not ts:
            continue
        if ccy not in newest_ts or ts > newest_ts[ccy]:
            newest_ts[ccy] = ts

    out = {}
    for r in offer_rows:
        ccy, ts, side = r.get("ccy"), r.get("ts_utc"), r.get("side")
        if not ccy or ts != newest_ts.get(ccy) or side != "buy":
            continue
        price = _f(r.get("price"))
        if price is None:
            continue
        out.setdefault(ccy, {"ts_utc": ts, "buy": []})["buy"].append(price)
    return out


def latest_depth_counts(depth_rows):
    """{ccy: (ts_utc, buy_total)} -- newest row per currency in p2p_depth.csv.

    Context only (see docstring, "THE FLOOR, AND WHY IT STAYS A FLOOR") --
    never used to extend a depth figure past what was actually priced.
    """
    best = {}
    for r in depth_rows:
        ccy, ts = r.get("ccy"), r.get("ts_utc")
        if not ccy or not ts:
            continue
        if ccy not in best or ts > best[ccy][0]:
            best[ccy] = (ts, _i(r.get("buy_total")))
    return best


def depth_for(prices, threshold_pct=THRESHOLD_PCT, filter_usd=FILTER_USD):
    """The cumulative depth, in dollars, before the board's own price would
    move by more than `threshold_pct` from its best offer.

    `prices` is one side's ads, board order, best first (see
    `latest_offer_board`). Each ad is treated as good for at least
    `filter_usd` -- the size the search was filtered to, per
    collector_p2p.py -- so `k` ads holding within the threshold is `k *
    filter_usd` of real depth, a lower bound, not an estimate rounded up.

    Returns None if there are no priced ads at all (an empty or unpriced
    board -- a real fact about that market, left as an absent entry by the
    caller rather than a fabricated zero).
    """
    if not prices:
        return None
    best = prices[0]
    if not best:
        return None
    n = len(prices)
    breach_idx = None
    for i in range(1, n):
        if abs(prices[i] - best) / best * 100.0 > threshold_pct:
            breach_idx = i
            break
    if breach_idx is not None:
        held = breach_idx
        marginal_price = prices[breach_idx]
        is_floor = False
    else:
        held = n
        marginal_price = prices[-1]
        is_floor = True
    return {
        "best_price": round(best, 8),
        "marginal_price": round(marginal_price, 8),
        "n_ads_priced": n,
        "n_ads_held": held,
        "depth_usd": held * filter_usd,
        "is_floor": is_floor,
    }


def build():
    boards = latest_offer_board(rows(OFFERS))
    counts = latest_depth_counts(rows(DEPTH_COUNTS))

    countries = {}
    for ccy, board in boards.items():
        d = depth_for(board["buy"])
        if d is None:
            continue
        entry = dict(d, ts_utc=board["ts_utc"], threshold_pct=THRESHOLD_PCT,
                     filter_usd=FILTER_USD, side="buy")
        buy_total_ts, buy_total = counts.get(ccy, (None, None))
        # Only attach the real board total when it is from the SAME hour --
        # a stale count is worse than none, and this must never look like it
        # backfilled a gap.
        if buy_total is not None and buy_total_ts == board["ts_utc"]:
            entry["buy_total_ads"] = buy_total
        countries[ccy] = entry

    stamps = [c["ts_utc"] for c in countries.values()]
    return {
        "threshold_pct": THRESHOLD_PCT,
        "filter_usd": FILTER_USD,
        "rows_fetched_per_side": ROWS,
        "method": (
            "Each fetched ad is treated as good for at least filter_usd of "
            "real size (the search's own amount filter). Walking the buy "
            "side in board order, depth_usd is the number of ads that hold "
            "within threshold_pct of the best ad's price, times filter_usd. "
            "is_floor=true means the fetched page never breached the "
            "threshold, so depth_usd is a lower bound, not the true depth."
        ),
        "sources": ["data/p2p_offers.csv", "data/p2p_depth.csv"],
        "as_of_utc": max(stamps) if stamps else None,
        "countries": countries,
    }


def main():
    doc = build()
    try:
        with open(OUT, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write {OUT}: {e}", file=sys.stderr)
        sys.exit(1)
    n = len(doc["countries"])
    floors = sum(1 for c in doc["countries"].values() if c["is_floor"])
    print(f"  wrote {OUT} ({n} currencies, threshold {THRESHOLD_PCT:g}%, "
          f"{floors} at the page floor, {n - floors} with a real crack found)")


if __name__ == "__main__":
    main()
