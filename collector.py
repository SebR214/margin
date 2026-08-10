#!/usr/bin/env python3
"""
margin.wiki collector -- corridor cost decomposition, sampled hourly.

Answers one question per sample: for a given corridor and size, what does the
stablecoin rail actually cost all-in, and how does that split between the
*rails* (network fee) and the *doors* (exchange execution + peg deviation)?

The public narrative measures the rail. Every real cost is at the doors.

What accumulates (and cannot be backfilled):
  - on-ramp basis   : where stable trades vs USD mid at the source venue
  - off-ramp basis  : where stable trades vs USD mid at the destination venue
  - book depth      : whether size moves the price at all
  - baseline margin : what the incumbent fiat rail charges at the same instant
  - fee config      : snapshotted per row, so history stays interpretable
                      when fee schedules change

Two execution regimes are recorded every sample, because the answer flips:
  TAKER -- crosses the spread, pays published taker fees. What retail does.
  MAKER -- posts and waits, zero trading fee. What size does.
           Upper bound: assumes fill at posted top-of-book, ignores fill risk.

Design constraints (deliberate):
  - flat CSV, stdlib + requests, no services to babysit
  - failures are RECORDED as rows with source_ok=false, never dropped;
    a gap in the chart must be visible as a gap, not absent
  - every derived number is a pure function, tested offline against real
    captured payloads in --selftest

Usage:
  python3 collector.py --verify     # one pull, print the waterfall, write nothing
  python3 collector.py              # one pull, append to data/samples.csv
  python3 collector.py --selftest   # offline, no network
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
    requests = None

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "data", "samples.csv")

# ---------------------------------------------------------------- config
# Fee schedules are the LARGEST single term in the decomposition. They are
# published numbers, not estimates -- but they must be verified against each
# venue's fee page and dated. Until verified, `verified` stays false and the
# methodology page must say so. See METHODOLOGY.md.
CORRIDORS = {
    "SGD->PHP": {
        "src": "SGD", "dst": "PHP", "stable": "USDT",
        "onramp": {
            "venue": "IndependentReserve",
            # 0.50% default tier (30-day volume < AUD 50k), flat brokerage fee.
            # IR publishes NO maker discount -- the maker=0 regime is optimistic
            # on this leg. Source: independentreserve.com/fees
            "taker_bps": 50.0,
            "verified": "2026-08-10",
        },
        "offramp": {
            "venue": "Coins.ph",
            "symbol": "USDTPHP",
            # VIP0 taker 0.15% effective 2025-08-08 (25 bps was assumed; wrong).
            # VIP0 maker is 0.10%, not zero. Source: support.coins.ph
            # article 11620285112217 (VIP fee table).
            "taker_bps": 15.0,
            "verified": "2026-08-10",
        },
        "network_fee_stable": 1.0,     # TRC20 USDT withdrawal, flat
        "ladder": [200, 1000, 5000, 25000, 50000],
    },
}

FIELDS = [
    "ts", "corridor", "src", "dst", "stable", "notional_src",
    # benchmark
    "mid_src_per_usd", "mid_dst_per_usd", "mid_src_dst",
    # on-ramp leg
    "onramp_venue", "onramp_top_ask", "onramp_vwap", "onramp_slip_bps",
    "onramp_filled", "onramp_basis_bps",
    # off-ramp leg
    "offramp_venue", "offramp_top_bid", "offramp_vwap", "offramp_slip_bps",
    "offramp_filled", "offramp_basis_bps",
    "offramp_depth_top_level", "offramp_depth_1pct",
    # fee regime in force for THIS row
    "fee_on_taker_bps", "fee_off_taker_bps", "network_fee_stable", "fees_verified",
    # outcomes
    "landed_taker", "cost_bps_taker", "landed_maker", "cost_bps_maker",
    "baseline_provider", "baseline_landed", "baseline_cost_bps",
    "crypto_wins_taker", "crypto_wins_maker",
    # provenance
    "source_ok", "errors",
]


# ------------------------------------------------------------- pure core
def norm_levels(raw):
    """Accept [[p,q],...] or [{'price':..,'volume':..},...]; return [(p,q)]."""
    out = []
    for lvl in raw or []:
        try:
            if isinstance(lvl, dict):
                p = next(lvl[k] for k in ("price", "Price") if k in lvl)
                q = next(lvl[k] for k in ("volume", "Volume", "qty", "quantity")
                         if k in lvl)
            else:
                p, q = lvl[0], lvl[1]
            p, q = float(p), float(q)
            if p > 0 and q > 0:
                out.append((p, q))
        except (StopIteration, KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def walk_buy(asks, budget):
    """Spend `budget` of quote, consuming asks ascending. -> (base, vwap, filled)."""
    base = spent = 0.0
    for p, q in asks:
        cost = p * q
        if spent + cost <= budget:
            base += q
            spent += cost
        else:
            rem = budget - spent
            base += rem / p
            spent = budget
            return base, (spent / base if base else None), True
    return base, (spent / base if base else None), False


def walk_sell(bids, amount):
    """Sell `amount` of base, consuming bids descending. -> (quote, vwap, filled)."""
    quote = sold = 0.0
    for p, q in bids:
        if sold + q <= amount:
            quote += p * q
            sold += q
        else:
            quote += p * (amount - sold)
            sold = amount
            return quote, (quote / sold if sold else None), True
    return quote, (quote / sold if sold else None), False


def depth_within_pct(bids, pct=0.01):
    """Base units sellable before price falls `pct` below top-of-book."""
    if not bids:
        return 0.0
    floor = bids[0][0] * (1 - pct)
    return sum(q for p, q in bids if p >= floor)


def bps(x):
    return None if x is None else round(x * 1e4, 2)


def basis_bps_cost(venue_price, usd_mid, side):
    """
    Peg deviation expressed as a COST in bps (positive = you lose).

    side='buy'  : you pay `venue_price` of local per stable. Above USD mid = loss.
    side='sell' : you receive `venue_price` of local per stable. Below mid = loss.
    """
    if not venue_price or not usd_mid:
        return None
    if side == "buy":
        return bps((venue_price - usd_mid) / usd_mid)
    return bps((usd_mid - venue_price) / usd_mid)


def decompose(notional, on_book, off_book, mids, cfg):
    """
    Full round trip for one notional under both execution regimes.
    Pure: takes parsed books + rates, returns a dict. No I/O.
    """
    src_usd, dst_usd = mids["src_per_usd"], mids["dst_per_usd"]
    mid = dst_usd / src_usd if (src_usd and dst_usd) else None

    on_fee = cfg["onramp"]["taker_bps"] / 1e4
    off_fee = cfg["offramp"]["taker_bps"] / 1e4
    netfee = cfg["network_fee_stable"]

    asks, bids = on_book.get("asks", []), off_book.get("bids", [])
    top_ask = asks[0][0] if asks else None
    top_bid = bids[0][0] if bids else None

    out = {
        "mid_src_dst": round(mid, 6) if mid else None,
        "onramp_top_ask": top_ask,
        "offramp_top_bid": top_bid,
        "onramp_basis_bps": basis_bps_cost(top_ask, src_usd, "buy"),
        "offramp_basis_bps": basis_bps_cost(top_bid, dst_usd, "sell"),
        "offramp_depth_top_level": bids[0][1] if bids else None,
        "offramp_depth_1pct": round(depth_within_pct(bids), 2) if bids else None,
    }

    gross, on_vwap, on_filled = walk_buy(asks, notional)
    out["onramp_vwap"] = round(on_vwap, 6) if on_vwap else None
    out["onramp_filled"] = on_filled
    out["onramp_slip_bps"] = (bps((on_vwap - top_ask) / top_ask)
                              if (on_vwap and top_ask) else None)

    for regime, fee_on, fee_off in (("taker", on_fee, off_fee), ("maker", 0.0, 0.0)):
        stable = gross * (1 - fee_on) - netfee
        if stable <= 0:
            out[f"landed_{regime}"] = 0.0
            out[f"cost_bps_{regime}"] = None
            if regime == "taker":
                out["offramp_vwap"] = out["offramp_slip_bps"] = None
                out["offramp_filled"] = False
            continue
        quote, off_vwap, off_filled = walk_sell(bids, stable)
        landed = quote * (1 - fee_off)
        out[f"landed_{regime}"] = round(landed, 2)
        out[f"cost_bps_{regime}"] = (bps(1 - landed / (notional * mid))
                                     if (mid and notional) else None)
        if regime == "taker":
            out["offramp_vwap"] = round(off_vwap, 6) if off_vwap else None
            out["offramp_filled"] = off_filled
            out["offramp_slip_bps"] = (bps((top_bid - off_vwap) / top_bid)
                                       if (off_vwap and top_bid) else None)
    return out


def pick_baseline(quotes):
    """Best incumbent fiat rail at this instant -> (name, landed)."""
    if not quotes:
        return None, None
    best = max(quotes, key=lambda q: q[1])
    return best[0], best[1]


def parse_wise(payload):
    """Wise comparison API -> [(provider, landed), ...]."""
    out = []
    for p in payload.get("providers", []):
        name = p.get("name") or p.get("alias")
        for q in p.get("quotes", []):
            amt = q.get("receivedAmount")
            if amt is None and q.get("rate") is not None:
                amt = (q.get("sourceAmount") or 0) - (q.get("fee") or 0)
                amt *= q["rate"]
            if name and amt:
                out.append((name, float(amt)))
    return out


# ------------------------------------------------------------------ I/O
def get_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_mids(src, dst):
    """USD-base mids for both legs, from one call. -> {src_per_usd, dst_per_usd}."""
    d = get_json("https://open.er-api.com/v6/latest/USD")
    rates = d.get("rates") or {}
    return {"src_per_usd": float(rates[src]), "dst_per_usd": float(rates[dst])}


def fetch_onramp(cfg, src):
    stable = cfg["stable"].capitalize()
    d = get_json("https://api.independentreserve.com/Public/GetOrderBook"
                 f"?primaryCurrencyCode={stable}&secondaryCurrencyCode={src.capitalize()}")
    asks = sorted(norm_levels(d.get("SellOrders")), key=lambda x: x[0])
    return {"asks": asks}


def fetch_offramp(cfg):
    # NOTE: api.pro.coins.ph -- `api.coins.ph` is NXDOMAIN and silently killed
    # 34 days of collection. Do not "simplify" this hostname.
    sym = cfg["offramp"]["symbol"]
    d = get_json(f"https://api.pro.coins.ph/openapi/quote/v1/depth?symbol={sym}&limit=200")
    bids = sorted(norm_levels(d.get("bids")), key=lambda x: x[0], reverse=True)
    return {"bids": bids}


def fetch_baseline(src, dst, amount):
    d = get_json("https://api.wise.com/v3/comparisons"
                 f"?sourceCurrency={src}&targetCurrency={dst}&sendAmount={amount}")
    return parse_wise(d)


# ------------------------------------------------------------- collection
def collect(corridor_key, cfg):
    """One sample across the whole ladder. Never raises; records failures."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    src, dst = cfg["src"], cfg["dst"]
    errors, ok = [], True

    try:
        mids = fetch_mids(src, dst)
    except Exception as e:
        errors.append(f"mid:{type(e).__name__}:{e}")
        mids, ok = {"src_per_usd": None, "dst_per_usd": None}, False

    try:
        on_book = fetch_onramp(cfg, src)
    except Exception as e:
        errors.append(f"onramp:{type(e).__name__}:{e}")
        on_book, ok = {"asks": []}, False

    try:
        off_book = fetch_offramp(cfg)
    except Exception as e:
        errors.append(f"offramp:{type(e).__name__}:{e}")
        off_book, ok = {"bids": []}, False

    fees_verified = "|".join(
        f"{k}:{cfg[k].get('verified') or 'UNVERIFIED'}" for k in ("onramp", "offramp"))

    rows = []
    for notional in cfg["ladder"]:
        d = decompose(notional, on_book, off_book, mids, cfg)

        try:
            quotes = fetch_baseline(src, dst, notional)
            bname, blanded = pick_baseline(quotes)
        except Exception as e:
            errors.append(f"baseline@{notional}:{type(e).__name__}:{e}")
            bname, blanded, ok = None, None, False

        mid = d["mid_src_dst"]
        bcost = bps(1 - blanded / (notional * mid)) if (blanded and mid) else None

        rows.append({
            "ts": ts, "corridor": corridor_key, "src": src, "dst": dst,
            "stable": cfg["stable"], "notional_src": notional,
            "mid_src_per_usd": mids["src_per_usd"], "mid_dst_per_usd": mids["dst_per_usd"],
            "onramp_venue": cfg["onramp"]["venue"], "offramp_venue": cfg["offramp"]["venue"],
            "fee_on_taker_bps": cfg["onramp"]["taker_bps"],
            "fee_off_taker_bps": cfg["offramp"]["taker_bps"],
            "network_fee_stable": cfg["network_fee_stable"],
            "fees_verified": fees_verified,
            "baseline_provider": bname, "baseline_landed": blanded,
            "baseline_cost_bps": bcost,
            "crypto_wins_taker": (None if (bcost is None or d["cost_bps_taker"] is None)
                                  else d["cost_bps_taker"] < bcost),
            "crypto_wins_maker": (None if (bcost is None or d["cost_bps_maker"] is None)
                                  else d["cost_bps_maker"] < bcost),
            "source_ok": ok, "errors": "; ".join(errors)[:500],
            **d,
        })
    return rows


def append(rows):
    os.makedirs(os.path.dirname(SAMPLES), exist_ok=True)
    new = not os.path.exists(SAMPLES)
    with open(SAMPLES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return SAMPLES


def print_waterfall(rows):
    if not rows:
        return
    r0 = rows[0]
    print(f"\n  {r0['corridor']}  via {r0['stable']}  "
          f"{r0['onramp_venue']} -> {r0['offramp_venue']}   {r0['ts'][:16]}Z")
    print(f"  mid {r0['mid_src_dst']}   "
          f"on-ramp basis {r0['onramp_basis_bps']:+} bps   "
          f"off-ramp basis {r0['offramp_basis_bps']:+} bps")
    if "UNVERIFIED" in (r0["fees_verified"] or ""):
        print("  !! fee schedules UNVERIFIED -- largest term in the stack")
    print("  " + "-" * 74)
    print(f"  {'SEND':>8}{'TAKER':>12}{'MAKER':>12}{'BASELINE':>12}"
          f"{'WINNER':>14}{'FILLED':>10}")
    print("  " + "-" * 74)
    for r in rows:
        t, m, b = r["cost_bps_taker"], r["cost_bps_maker"], r["baseline_cost_bps"]
        fmt = lambda v: f"{v:.0f}bps" if v is not None else "--"
        if None in (t, b):
            win = "--"
        elif t < b:
            win = "crypto (taker)"
        elif m is not None and m < b:
            win = "crypto (maker)"
        else:
            win = r["baseline_provider"] or "baseline"
        filled = "yes" if (r["onramp_filled"] and r["offramp_filled"]) else "THIN"
        print(f"  {r['notional_src']:>8,}{fmt(t):>12}{fmt(m):>12}{fmt(b):>12}"
              f"{win:>14}{filled:>10}")
    print("  " + "-" * 74)
    print("  cost = bps below mid-market. maker = zero trading fee, assumes fill.\n")


# -------------------------------------------------------------- selftest
# Fixtures are REAL payloads captured 2026-08-10, not synthetic. This tests the
# parsers against the shapes the venues actually return -- the exact class of
# bug (wrong host / wrong shape) that killed the previous collector.
IR_FIXTURE = {"SellOrders": [
    {"Price": 1.2781, "Volume": 5000}, {"Price": 1.2785, "Volume": 2912.05491},
    {"Price": 1.27857, "Volume": 65894.96562}]}
COINS_FIXTURE = {"bids": [
    ["60.680000000000000000", "268022.060000000000000000"],
    ["60.670000000000000000", "56845.970000000000000000"],
    ["60.660000000000000000", "122172.710000000000000000"]]}
MIDS_FIXTURE = {"src_per_usd": 1.279634, "dst_per_usd": 60.857717}


def selftest():
    cfg = CORRIDORS["SGD->PHP"]

    on = {"asks": sorted(norm_levels(IR_FIXTURE["SellOrders"]), key=lambda x: x[0])}
    off = {"bids": sorted(norm_levels(COINS_FIXTURE["bids"]),
                          key=lambda x: x[0], reverse=True)}
    assert on["asks"][0] == (1.2781, 5000.0), on["asks"][:1]
    assert off["bids"][0] == (60.68, 268022.06), off["bids"][:1]
    print("  [ok] parsers handle both real payload shapes (dict + string-array)")

    d = decompose(5000, on, off, MIDS_FIXTURE, cfg)

    assert abs(d["mid_src_dst"] - 47.5587) < 1e-3, d["mid_src_dst"]
    assert abs(d["onramp_basis_bps"] - (-12.0)) < 0.5, d["onramp_basis_bps"]
    assert abs(d["offramp_basis_bps"] - 29.2) < 0.5, d["offramp_basis_bps"]
    print(f"  [ok] basis: on-ramp {d['onramp_basis_bps']:+} bps (stable cheap in SG), "
          f"off-ramp {d['offramp_basis_bps']:+} bps (stable cheap in PH)")

    # 84.6 with verified fees (IR 50 + Coins 15); was 94.8 under the assumed
    # 25 bps Coins taker fee before verification on 2026-08-10.
    assert abs(d["cost_bps_taker"] - 84.6) < 1.0, d["cost_bps_taker"]
    assert abs(d["cost_bps_maker"] - 19.8) < 1.0, d["cost_bps_maker"]
    print(f"  [ok] regimes diverge: taker {d['cost_bps_taker']:.1f} bps vs "
          f"maker {d['cost_bps_maker']:.1f} bps -- same book, same second")

    # the decomposition must reconcile to the taker total
    parts = (d["onramp_basis_bps"] + cfg["onramp"]["taker_bps"]
             + cfg["network_fee_stable"] / (5000 / on["asks"][0][0]) * 1e4
             + d["offramp_basis_bps"] + cfg["offramp"]["taker_bps"])
    assert abs(parts - d["cost_bps_taker"]) < 1.5, (parts, d["cost_bps_taker"])
    print(f"  [ok] waterfall reconciles: parts {parts:.1f} == total "
          f"{d['cost_bps_taker']:.1f} bps")

    # small size: the flat network fee should dominate
    small = decompose(200, on, off, MIDS_FIXTURE, cfg)
    net_small = cfg["network_fee_stable"] / (200 / on["asks"][0][0]) * 1e4
    assert net_small > 60, net_small
    assert small["cost_bps_taker"] > d["cost_bps_taker"] + 50, small["cost_bps_taker"]
    print(f"  [ok] size effect: at S$200 the flat network fee alone is "
          f"{net_small:.0f} bps ({small['cost_bps_taker']:.0f} bps all-in)")

    # depth: at this book, ladder sizes do not move the price
    assert d["offramp_slip_bps"] == 0.0, d["offramp_slip_bps"]
    assert d["offramp_filled"] and d["onramp_filled"]
    print(f"  [ok] depth: 0.0 bps slippage at S$5k; top level holds "
          f"{d['offramp_depth_top_level']:,.0f} USDT")

    # thin book must be flagged, never silently truncated
    thin = decompose(5000, on, {"bids": [(60.68, 10.0)]}, MIDS_FIXTURE, cfg)
    assert thin["offramp_filled"] is False
    print("  [ok] thin book flagged (filled=False), not silently truncated")

    # total failure still yields a well-formed row, not a crash
    dead = decompose(5000, {"asks": []}, {"bids": []}, MIDS_FIXTURE, cfg)
    assert dead["landed_taker"] == 0.0 and dead["onramp_top_ask"] is None
    print("  [ok] dead sources degrade to a recorded row, not an exception")

    assert set(FIELDS) >= set(dead) | {"ts", "corridor", "source_ok", "errors"}
    print("  [ok] schema covers every derived field\n")
    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki corridor collector")
    ap.add_argument("--corridor", default="SGD->PHP", choices=list(CORRIDORS))
    ap.add_argument("--verify", action="store_true",
                    help="one pull, print waterfall, write nothing (RUN THIS FIRST)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    rows = collect(a.corridor, CORRIDORS[a.corridor])

    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_waterfall(rows)

    if not rows[0]["source_ok"]:
        print(f"  [warn] incomplete sample: {rows[0]['errors']}", file=sys.stderr)

    if not a.verify:
        print(f"  appended -> {append(rows)}\n")
        # exit non-zero on a dead sample so the scheduler surfaces it loudly
        # instead of quietly accumulating empty rows for a month
        if not rows[0]["source_ok"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
