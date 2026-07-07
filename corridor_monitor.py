#!/usr/bin/env python3
"""
SEA Corridor Monitor  --  v0 (SGD -> PHP)

Tracks the REAL cost of moving money across rails and reports the spread.
Everything is normalized to one number: "send N SGD, how many PHP actually land."

Rails:
  1. Wise comparison API  -> Wise + several competitor remittance providers
                             (real fee + real rate + real received amount, one call)
  2. Stablecoin round-trip -> SGD -> USDT (on-ramp) -> USDT -> PHP (off-ramp),
                             computed by WALKING REAL ORDER BOOKS:
                               - SG on-ramp:  Independent Reserve GetOrderBook (public, keyless)
                               - PH off-ramp: Coins.ph depth (public, Binance-style)
                             The received amount is the actual fill for a S$1,000 notional,
                             including slippage on the thin PH book -- the cost everyone
                             else's comparison hides. Trading/withdrawal fees are published
                             numbers, exposed as knobs. If a book can't be fetched, the rail
                             degrades to a labeled parametric model rather than lying.

Thesis: this is the OBSERVABLE cost of moving money SGD->PHP. The retail path
(exchange books + published fees) is fully computable; what's proprietary is the
enterprise payout layer (Nium/Thunes/Circle negotiated rates), which is out of
scope by nature and noted as such.

Benchmark: mid-market SGD->PHP rate (keyless FX API). Cost is measured as the
margin (%) each rail charges vs mid-market, plus the spread of each rail vs the
cheapest rail in the run.

Usage:
  python3 corridor_monitor.py                 # run once, print table, append snapshot
  python3 corridor_monitor.py --amount 5000   # different notional
  python3 corridor_monitor.py --selftest      # offline math check, no network
  python3 corridor_monitor.py --json          # machine-readable output for a dashboard

Only dependency: requests  (pip install requests)
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None  # only needed for live mode; --selftest works without it

HTTP_TIMEOUT = 20
SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots.csv")
OFFRAMP_SNAPSHOT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "offramp_snapshots.csv")
OFFRAMP_FIELDS = [
    "ts", "corridor", "leg", "venue", "stable", "notional_src", "notional_src_ccy",
    "notional_stable", "top_of_book_rate", "achievable_rate", "slippage_bps_vs_top",
    "depth_to_1pct_slippage", "book_levels_used", "filled_fully", "source_ok",
]

# ------------------------------------------------------------------ mid-market

def fetch_mid_rate(src="SGD", dst="PHP"):
    """Mid-market rate (units of dst per 1 src) from a keyless FX API, with fallback."""
    endpoints = [
        f"https://open.er-api.com/v6/latest/{src}",           # primary, keyless
        f"https://api.exchangerate.host/latest?base={src}",   # fallback
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            rates = data.get("rates") or data.get("conversion_rates") or {}
            if dst in rates and rates[dst]:
                return float(rates[dst]), url
        except Exception:
            continue
    raise RuntimeError("Could not fetch mid-market rate from any FX source")


def fetch_usd_per_sgd(src="SGD"):
    """USD per 1 unit of `src`, to size the off-ramp walk in USDT (USDT ~ USD)."""
    rate, _ = fetch_mid_rate(src, "USD")
    return rate


# --------------------------------------------------------------------- Wise

def fetch_wise_quotes(src, dst, amount):
    """
    Wise comparison API. Returns a list of rail dicts.
    The endpoint returns Wise AND competing providers (banks, remittance cos),
    each with a real rate, fee and received amount -- a de facto aggregator.
    """
    url = (
        "https://api.wise.com/v1/comparisons"
        f"?sourceCurrency={src}&targetCurrency={dst}&sendAmount={amount}"
    )
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "corridor-monitor/0.1"})
    r.raise_for_status()
    return parse_wise_quotes(r.json(), amount)


def parse_wise_quotes(payload, amount):
    """Pure parser (unit-tested offline)."""
    rails = []
    for provider in payload.get("providers", []):
        name = provider.get("name") or provider.get("alias") or "unknown"
        for q in provider.get("quotes", []):
            received = q.get("receivedAmount")
            rate = q.get("rate")
            fee = q.get("fee")
            if received is None and rate is not None:
                received = (amount - (fee or 0)) * rate
            if received is None:
                continue
            rails.append({
                "rail": name,
                "kind": "fiat",
                "php_received": round(float(received), 2),
                "fee_src": float(fee) if fee is not None else None,
                "quoted_rate": float(rate) if rate is not None else None,
                "source": "wise_comparison_api",
            })
    return rails


# ------------------------------------------------- order-book walking engine
# The core of the differentiated rail: compute the ACTUAL fill for a notional by
# consuming real depth level-by-level, so slippage on a thin book is captured
# rather than modeled. Pure functions -> unit-tested offline in --selftest.

def walk_asks_spend(asks, quote_budget):
    """
    BUY base by spending `quote_budget` of quote currency, consuming asks
    (ascending price). asks: list of (price, qty) where price = quote per base.
    Returns (base_received, quote_spent, filled_fully).
    filled_fully is False if the book ran out before the budget was spent.
    """
    base = 0.0
    spent = 0.0
    for price, qty in asks:
        if price <= 0 or qty <= 0:
            continue
        level_cost = price * qty
        if spent + level_cost <= quote_budget:
            base += qty
            spent += level_cost
        else:
            remaining = quote_budget - spent
            base += remaining / price
            return base, quote_budget, True
    return base, spent, False


def walk_bids_sell(bids, base_amount):
    """
    SELL `base_amount` of base, consuming bids (descending price).
    bids: list of (price, qty), price = quote per base.
    Returns (quote_received, base_sold, filled_fully).
    """
    quote = 0.0
    sold = 0.0
    for price, qty in bids:
        if price <= 0 or qty <= 0:
            continue
        if sold + qty <= base_amount:
            quote += price * qty
            sold += qty
        else:
            remaining = base_amount - sold
            quote += price * remaining
            return quote, base_amount, True
    return quote, sold, False


# --------------------------------------------------------- venue adapters
# NOTE: field names below follow each venue's documented shape. Parsers are
# tolerant (accept [price,qty] lists OR {price,qty}/{Price,Volume} dicts).
# Verify against the first real response and adjust if a venue differs.

def _norm_levels(raw, price_keys=("price", "Price", 0), qty_keys=("qty", "Volume", "quantity", 1)):
    out = []
    for lvl in raw or []:
        try:
            if isinstance(lvl, dict):
                p = next(lvl[k] for k in price_keys if k in lvl)
                q = next(lvl[k] for k in qty_keys if k in lvl)
            else:  # list/tuple like ["57.10", "1000"]
                p, q = lvl[0], lvl[1]
            out.append((float(p), float(q)))
        except (StopIteration, KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def parse_ir_book(payload):
    """
    Independent Reserve GetOrderBook. To BUY the stable coin we consume the
    SellOrders (offers), priced in SGD per unit. Returns asks ascending.
    """
    asks = _norm_levels(payload.get("SellOrders"))
    bids = _norm_levels(payload.get("BuyOrders"))
    asks.sort(key=lambda x: x[0])
    bids.sort(key=lambda x: x[0], reverse=True)
    return {"asks": asks, "bids": bids}


def parse_coins_book(payload):
    """Coins.ph depth (Binance-style): {'bids':[[p,q]...], 'asks':[[p,q]...]}."""
    asks = _norm_levels(payload.get("asks"))
    bids = _norm_levels(payload.get("bids"))
    asks.sort(key=lambda x: x[0])
    bids.sort(key=lambda x: x[0], reverse=True)
    return {"asks": asks, "bids": bids}


def fetch_ir_book(stable="Usdt", fiat="Sgd"):
    url = ("https://api.independentreserve.com/Public/GetOrderBook"
           f"?primaryCurrencyCode={stable}&secondaryCurrencyCode={fiat}")
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "corridor-monitor/0.2"})
    r.raise_for_status()
    return parse_ir_book(r.json())


def fetch_coins_book(symbol="USDTPHP", limit=200):
    url = f"https://api.coins.ph/openapi/quote/v1/depth?symbol={symbol}&limit={limit}"
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "corridor-monitor/0.2"})
    r.raise_for_status()
    return parse_coins_book(r.json())


# ----------------------------------------------- real stablecoin round-trip

def stablecoin_rail(amount_sgd, on_book, off_book, fees, stable="USDT",
                    venue_on="IndependentReserve", venue_off="Coins.ph"):
    """
    SGD -> stable (SG on-ramp) -> stable -> PHP (PH off-ramp), from REAL books.
    fees: {on_taker, off_taker, network_fee_stable, php_withdraw}.
    Reports off-ramp slippage vs top-of-book -- the headline cost.
    """
    notes = []
    # Leg 1: buy `stable` with SGD on the SG venue.
    base_gross, sgd_spent, ok1 = walk_asks_spend(on_book["asks"], amount_sgd)
    stable_amt = base_gross * (1 - fees["on_taker"])
    stable_amt -= fees["network_fee_stable"]           # withdrawal to PH venue
    if not ok1:
        notes.append("SG on-ramp book too thin for notional")

    # Leg 2: sell `stable` for PHP on the PH venue.
    best_bid = off_book["bids"][0][0] if off_book["bids"] else None
    php_gross, sold, ok2 = walk_bids_sell(off_book["bids"], max(stable_amt, 0.0))
    php = php_gross * (1 - fees["off_taker"])
    php -= fees["php_withdraw"]                          # InstaPay/PESONet cash-out
    if not ok2:
        notes.append("PH off-ramp book too thin for notional")

    avg_off = (php_gross / sold) if sold else None
    off_slip = round((best_bid - avg_off) / best_bid * 100, 3) if (best_bid and avg_off) else None

    return {
        "rail": f"Stablecoin ({stable}) {venue_on}->{venue_off}",
        "kind": "crypto",
        "php_received": round(max(php, 0.0), 2),
        "fee_src": None,
        "quoted_rate": round(max(php, 0.0) / amount_sgd, 4),
        "offramp_slippage_pct": off_slip,
        "source": (f"orderbook(on={venue_on},off={venue_off},stable={stable},"
                   f"on_taker={fees['on_taker']},off_taker={fees['off_taker']},"
                   f"netfee={fees['network_fee_stable']}{stable},"
                   f"php_withdraw={fees['php_withdraw']})"
                   + (" | " + "; ".join(notes) if notes else "")),
    }


def model_stable_rail(amount_sgd, mid_rate, p):
    """
    Fallback ONLY when real books can't be fetched. Clearly labeled as a model so
    it never masquerades as observed data. Parametric spreads instead of depth.
    """
    php = amount_sgd * mid_rate * (1 - p["on_taker"] - p["off_taker"] - 0.004)
    php -= p["php_withdraw"]
    return {
        "rail": "Stablecoin round-trip (MODELED fallback)",
        "kind": "crypto",
        "php_received": round(max(php, 0.0), 2),
        "fee_src": None,
        "quoted_rate": round(max(php, 0.0) / amount_sgd, 4),
        "offramp_slippage_pct": None,
        "source": "MODEL_FALLBACK(no live book) " + json.dumps(p),
    }


# ============================================================================
#  OFF-RAMP DEPTH SNAPSHOT  --  the differentiated core (v1 headline)
#  For each notional in the ladder, walk the real PH off-ramp book and record
#  the achievable rate + slippage + depth. This is the time series nobody
#  publishes; the schema is venue-generic so adding a venue never resets history.
# ============================================================================

def depth_metrics(bids, base_notional):
    """
    Sell `base_notional` of stable into `bids` (descending). Returns the
    achievable VWAP and slippage vs top-of-book. Pure -> unit-tested offline.
    """
    if not bids or base_notional <= 0:
        return None
    best = bids[0][0]
    quote = 0.0
    sold = 0.0
    levels = 0
    for price, qty in bids:
        if price <= 0 or qty <= 0:
            continue
        levels += 1
        if sold + qty <= base_notional:
            quote += price * qty
            sold += qty
        else:
            quote += price * (base_notional - sold)
            sold = base_notional
            break
    vwap = quote / sold if sold else None
    slip_bps = (best - vwap) / best * 1e4 if vwap else None
    return {
        "best_bid": best,
        "vwap": vwap,
        "slippage_bps": slip_bps,
        "filled_fully": sold >= base_notional - 1e-9,
        "levels_used": levels,
        "base_sold": sold,
    }


def depth_within_pct(bids, pct=0.01):
    """Total stable (base) you can sell before price drops `pct` below top-of-book."""
    if not bids:
        return 0.0
    thr = bids[0][0] * (1 - pct)
    return sum(q for p, q in bids if p >= thr and q > 0)


def build_offramp_row(ts, src, dst, venue, stable, notional_src, notional_stable,
                      bids, source_ok):
    m = depth_metrics(bids, notional_stable) if (notional_stable and bids) else None
    return {
        "ts": ts,
        "corridor": f"{src}->{dst}",
        "leg": "off-ramp",
        "venue": venue,
        "stable": stable,
        "notional_src": notional_src,
        "notional_src_ccy": src,
        "notional_stable": round(notional_stable, 2) if notional_stable else None,
        "top_of_book_rate": round(m["best_bid"], 4) if m else None,
        "achievable_rate": round(m["vwap"], 4) if (m and m["vwap"]) else None,
        "slippage_bps_vs_top": round(m["slippage_bps"], 2) if (m and m["slippage_bps"] is not None) else None,
        "depth_to_1pct_slippage": round(depth_within_pct(bids), 2) if bids else None,
        "book_levels_used": m["levels_used"] if m else 0,
        "filled_fully": m["filled_fully"] if m else False,
        "source_ok": source_ok,
    }


# venue registry: name -> callable(stable, dst) returning parsed book {asks,bids}
OFFRAMP_VENUES = {
    "Coins.ph": lambda stable, dst: fetch_coins_book(symbol=f"{stable}{dst}"),
    # "PDAX": ...        # add once public access is confirmed
    # "Binance P2P": ... # first expansion; ad-listing, not a book
}


def run_offramp_snapshot(args):
    if requests is None:
        sys.exit("The 'requests' package is required: pip install requests")
    src, dst, stable = args.src, args.dst.upper(), args.stable.upper()
    ladder = [float(x) for x in args.ladder.split(",") if x.strip()]
    ts = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        usd_per_sgd = fetch_usd_per_sgd(src)
    except Exception as e:
        print(f"  [warn] USD/{src} rate failed ({e}); notional_stable will be null",
              file=sys.stderr)
        usd_per_sgd = None

    rows = []
    for venue, fetch in OFFRAMP_VENUES.items():
        try:
            book = fetch(stable, dst)
            ok = True
        except Exception as e:
            print(f"  [warn] {venue} book failed: {e}", file=sys.stderr)
            book, ok = {"asks": [], "bids": []}, False
        for notional_src in ladder:
            notional_stable = notional_src * usd_per_sgd if usd_per_sgd else None
            rows.append(build_offramp_row(ts, src, dst, venue, stable,
                                          notional_src, notional_stable,
                                          book.get("bids", []), ok))

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_offramp_table(rows, src, dst, stable)
    if not args.no_store:
        path = append_offramp_snapshot(rows)
        if not args.json:
            print(f"  snapshot appended -> {path}\n")


def print_offramp_table(rows, src, dst, stable):
    print()
    print(f"  OFF-RAMP DEPTH  {stable}->{dst}   {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%MZ}")
    print("  " + "-" * 82)
    print(f"  {'VENUE':<12}{'SEND '+src:>10}{'ACHIEVED '+dst+'/'+stable:>20}"
          f"{'SLIP(bps)':>11}{'DEPTH<1%':>13}{'FILL':>6}")
    print("  " + "-" * 82)
    for r in rows:
        ach = f"{r['achievable_rate']:.4f}" if r["achievable_rate"] else "--"
        slip = f"{r['slippage_bps_vs_top']:.1f}" if r["slippage_bps_vs_top"] is not None else "--"
        depth = f"{r['depth_to_1pct_slippage']:,.0f}" if r["depth_to_1pct_slippage"] is not None else "--"
        fill = "yes" if r["filled_fully"] else "THIN"
        print(f"  {r['venue'][:11]:<12}{r['notional_src']:>10,.0f}{ach:>20}"
              f"{slip:>11}{depth:>13}{fill:>6}")
    print("  " + "-" * 82)


def append_offramp_snapshot(rows):
    os.makedirs(os.path.dirname(OFFRAMP_SNAPSHOT_FILE), exist_ok=True)
    new = not os.path.exists(OFFRAMP_SNAPSHOT_FILE)
    with open(OFFRAMP_SNAPSHOT_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OFFRAMP_FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    return OFFRAMP_SNAPSHOT_FILE


# --------------------------------------------------------------- normalize

def normalize(rails, amount_sgd, mid_rate):
    """Attach effective rate, margin-vs-mid, and spread-vs-best to every rail."""
    if not rails:
        return rails
    best = max(r["php_received"] for r in rails)
    for r in rails:
        eff = r["php_received"] / amount_sgd
        r["effective_rate"] = round(eff, 4)
        r["margin_vs_mid_pct"] = round((mid_rate - eff) / mid_rate * 100, 3)
        r["spread_vs_best_pct"] = round((best - r["php_received"]) / best * 100, 3)
    rails.sort(key=lambda r: r["php_received"], reverse=True)
    return rails


# ------------------------------------------------------------------ output

def print_table(rails, amount_sgd, mid_rate, src, dst):
    print()
    print(f"  {src} -> {dst}   send {amount_sgd:,.0f} {src}   "
          f"mid-market {mid_rate:.4f}   {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%MZ}")
    print("  " + "-" * 84)
    print(f"  {'RAIL':<28}{dst+' RECEIVED':>15}{'EFF RATE':>11}"
          f"{'vs MID':>9}{'vs BEST':>10}")
    print("  " + "-" * 84)
    for r in rails:
        print(f"  {r['rail'][:27]:<28}{r['php_received']:>15,.2f}"
              f"{r['effective_rate']:>11.4f}{r['margin_vs_mid_pct']:>8.2f}%"
              f"{r['spread_vs_best_pct']:>9.2f}%")
    print("  " + "-" * 84)
    if len(rails) > 1:
        best, worst = rails[0], rails[-1]
        gap = best["php_received"] - worst["php_received"]
        print(f"  Best: {best['rail']}  ({best['php_received']:,.2f} {dst}).  "
              f"Spread best->worst: {gap:,.2f} {dst} "
              f"({worst['spread_vs_best_pct']:.2f}%).")
    for r in rails:
        slip = r.get("offramp_slippage_pct")
        if slip is not None:
            print(f"  {dst} off-ramp slippage on '{r['rail']}': {slip:.2f}% "
                  f"(cost hidden by the '10-cent transfer' pitch).")
    print()


def append_snapshot(rails, amount_sgd, mid_rate, src, dst):
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    new = not os.path.exists(SNAPSHOT_FILE)
    with open(SNAPSHOT_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "src", "dst", "amount_src", "mid_rate", "rail", "kind",
                        "dst_received", "effective_rate", "margin_vs_mid_pct",
                        "spread_vs_best_pct", "offramp_slippage_pct", "source"])
        for r in rails:
            w.writerow([ts, src, dst, amount_sgd, mid_rate, r["rail"], r["kind"],
                        r["php_received"], r["effective_rate"], r["margin_vs_mid_pct"],
                        r["spread_vs_best_pct"], r.get("offramp_slippage_pct"), r["source"]])
    return SNAPSHOT_FILE


# --------------------------------------------------------------------- run

def run(args):
    if requests is None:
        sys.exit("The 'requests' package is required for live mode: pip install requests")
    src, dst, amount = args.src, args.dst, args.amount
    mid_rate, mid_src = fetch_mid_rate(src, dst)

    rails = []
    try:
        rails += fetch_wise_quotes(src, dst, amount)
    except Exception as e:
        print(f"  [warn] Wise comparison API failed: {e}", file=sys.stderr)

    fees = {"on_taker": args.on_taker, "off_taker": args.off_taker,
            "network_fee_stable": args.network_fee_stable,
            "php_withdraw": args.php_withdraw}
    try:
        on_book = fetch_ir_book(stable=args.stable.capitalize(), fiat=src.capitalize())
        off_book = fetch_coins_book(symbol=f"{args.stable.upper()}{dst.upper()}")
        rails.append(stablecoin_rail(amount, on_book, off_book, fees, stable=args.stable.upper()))
    except Exception as e:
        print(f"  [warn] live order books unavailable ({e}); using MODELED fallback",
              file=sys.stderr)
        rails.append(model_stable_rail(amount, mid_rate, fees))

    rails = normalize(rails, amount, mid_rate)

    if args.json:
        print(json.dumps({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "src": src, "dst": dst, "amount": amount,
            "mid_rate": mid_rate, "mid_source": mid_src, "rails": rails,
        }, indent=2))
    else:
        print_table(rails, amount, mid_rate, src, dst)

    if not args.no_store:
        path = append_snapshot(rails, amount, mid_rate, src, dst)
        if not args.json:
            print(f"  snapshot appended -> {path}\n")


# ------------------------------------------------------------------ selftest

def selftest():
    """Offline validation of the math. No network."""
    ok = True

    # 1) Wise parser
    payload = {"providers": [
        {"name": "Wise", "quotes": [{"rate": 42.0, "fee": 6.0, "receivedAmount": 41748.0}]},
        {"name": "BankX", "quotes": [{"rate": 40.5, "fee": 0.0}]},  # no receivedAmount -> derive
    ]}
    parsed = parse_wise_quotes(payload, 1000)
    assert parsed[0]["php_received"] == 41748.0, parsed
    assert abs(parsed[1]["php_received"] - 40500.0) < 1e-6, parsed  # (1000-0)*40.5
    print("  [ok] Wise parser: receivedAmount honored + derived-when-missing")

    # 2) normalize: effective rate, margin vs mid, spread vs best
    mid = 42.5
    rails = [
        {"rail": "A", "kind": "fiat", "php_received": 42000.0, "source": "t"},
        {"rail": "B", "kind": "fiat", "php_received": 40000.0, "source": "t"},
    ]
    normalize(rails, 1000, mid)
    a = next(r for r in rails if r["rail"] == "A")
    b = next(r for r in rails if r["rail"] == "B")
    assert a["effective_rate"] == 42.0, a
    assert a["spread_vs_best_pct"] == 0.0, a           # A is best
    assert abs(b["spread_vs_best_pct"] - (2000/42000*100)) < 1e-3, b
    assert abs(a["margin_vs_mid_pct"] - (0.5/42.5*100)) < 1e-3, a
    assert rails[0]["rail"] == "A", "sorted best-first"
    print("  [ok] normalize: effective rate, margin-vs-mid, spread-vs-best, sort order")

    # 3) order-book walking: exact fill + slippage across levels
    asks = [(1.35, 100), (1.36, 100), (1.40, 1000)]  # SGD per USDT
    base, spent, full = walk_asks_spend(asks, 1000)
    # spend 135 + 136 = 271 on first 200 units, then 729 at 1.40 -> +520.71 units
    assert full and abs(spent - 1000) < 1e-9, (spent, full)
    assert abs(base - (200 + 729 / 1.40)) < 1e-6, base
    print(f"  [ok] walk_asks_spend: {base:,.2f} USDT for S$1,000 across 3 levels")

    bids = [(57.0, 100), (56.5, 100), (55.0, 1000)]  # PHP per USDT, descending
    quote, sold, full2 = walk_bids_sell(bids, 300)
    assert full2 and abs(sold - 300) < 1e-9
    assert abs(quote - (57.0 * 100 + 56.5 * 100 + 55.0 * 100)) < 1e-6, quote
    avg = quote / sold
    slip = (bids[0][0] - avg) / bids[0][0] * 100
    assert 0 < slip < 3, slip  # real, non-zero slippage below top of book
    print(f"  [ok] walk_bids_sell: avg {avg:.3f} PHP/USDT, {slip:.2f}% slippage vs best bid")

    # 4) thin book flagged, not silently truncated
    _, _, full3 = walk_bids_sell([(57.0, 10)], 300)  # only 10 available, want 300
    assert full3 is False
    print("  [ok] thin-book exhaustion flagged (full=False)")

    # 5) full round trip end-to-end + slippage reported
    on_book = {"asks": asks, "bids": []}
    off_book = {"asks": [], "bids": [(57.0, 50), (56.0, 500), (54.0, 5000)]}
    fees = {"on_taker": 0.005, "off_taker": 0.0025, "network_fee_stable": 1.0, "php_withdraw": 0.0}
    rt = stablecoin_rail(1000, on_book, off_book, fees, stable="USDT")
    assert rt["php_received"] > 0 and rt["offramp_slippage_pct"] is not None
    assert rt["php_received"] < 1000 * 57.0, "must be below top-of-book * notional"
    print(f"  [ok] round trip: {rt['php_received']:,.2f} PHP, "
          f"off-ramp slippage {rt['offramp_slippage_pct']:.2f}%")

    # 6) off-ramp depth metrics: VWAP, slippage, filled flag
    dbids = [(57.0, 100), (56.5, 100), (55.0, 1000)]
    m = depth_metrics(dbids, 300)
    assert abs(m["vwap"] - (57 * 100 + 56.5 * 100 + 55 * 100) / 300) < 1e-9, m
    assert abs(m["slippage_bps"] - (57 - m["vwap"]) / 57 * 1e4) < 1e-6, m
    assert m["filled_fully"] and m["levels_used"] == 3
    thin = depth_metrics([(57.0, 10)], 300)
    assert thin["filled_fully"] is False and thin["base_sold"] == 10
    print(f"  [ok] depth_metrics: VWAP {m['vwap']:.3f}, {m['slippage_bps']:.1f} bps, thin flagged")

    # 7) depth within 1% of top-of-book
    assert depth_within_pct(dbids, 0.01) == 200, depth_within_pct(dbids, 0.01)  # 57.0 & 56.5 only
    print("  [ok] depth_within_pct: sums only levels within 1% of best bid")

    # 8) snapshot row shape matches the venue-generic schema
    row = build_offramp_row("T", "SGD", "PHP", "Coins.ph", "USDT", 5000, 3700, dbids, True)
    assert set(row.keys()) == set(OFFRAMP_FIELDS), row.keys()
    assert row["filled_fully"] is False  # 3700 > total book depth 1200
    print("  [ok] build_offramp_row: schema-complete, thin book at size flagged")

    print("\n  ALL SELFTESTS PASSED\n" if ok else "\n  FAILURES\n")


# --------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="SEA corridor cost monitor (v0: SGD->PHP)")
    ap.add_argument("--src", default="SGD")
    ap.add_argument("--dst", default="PHP")
    ap.add_argument("--amount", type=float, default=1000.0, help="notional in --src currency")
    ap.add_argument("--stable", default="USDT", help="bridge stablecoin symbol (USDT/USDC)")
    ap.add_argument("--on-taker", dest="on_taker", type=float, default=0.005,
                    help="SG on-ramp taker fee (fraction; Independent Reserve ~0.5%%)")
    ap.add_argument("--off-taker", dest="off_taker", type=float, default=0.0025,
                    help="PH off-ramp taker fee (fraction; Coins.ph Pro ~0.25%%)")
    ap.add_argument("--network-fee-stable", dest="network_fee_stable", type=float, default=1.0,
                    help="fixed stablecoin withdrawal fee (units of --stable, e.g. TRC20 ~1)")
    ap.add_argument("--php-withdraw", dest="php_withdraw", type=float, default=0.0,
                    help="PHP cash-out fee (InstaPay/PESONet; often free, in PHP)")
    ap.add_argument("--offramp-snapshot", dest="offramp_snapshot", action="store_true",
                    help="v1 headline: sample off-ramp depth across the notional ladder")
    ap.add_argument("--ladder", default="1000,5000,10000,25000",
                    help="comma-separated --src notionals for the off-ramp depth sweep")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-store", action="store_true", help="do not append to snapshot file")
    ap.add_argument("--selftest", action="store_true", help="run offline math checks and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if args.offramp_snapshot:
        run_offramp_snapshot(args)
        return
    run(args)


if __name__ == "__main__":
    main()
