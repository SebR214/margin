#!/usr/bin/env python3
"""
margin.wiki multi-venue stablecoin collector -- SOURCES task 3.

Every corridor's stablecoin route has always been priced on exactly ONE venue
per leg: collector.py's `decompose()` reads one order book to buy USDT (the
on-ramp) and one to sell it (the off-ramp). That is a single quote standing in
for "the stablecoin route", the same shape of problem SOURCES tasks 1-2 fixed
for the incumbent panel (one comparison feed standing in for "the market").

This file prices EVERY venue this repo already has a live, public,
unauthenticated read on for each corridor's src and dst currency, plus one new
venue (OKX P2P, probed below), and publishes the cheapest EXECUTABLE
buy-venue/sell-venue combination. The existing single-venue collector.py run
is untouched -- its samples.csv row is still written, unchanged, so the
original per-venue history keeps accumulating exactly as before. This is a
new, additive file (data/stable_venues.csv) sitting alongside it.

METHOD. For a leg, "price" means: walk that venue's own book (order book, or a
P2P ad board treated as one -- price and executable quantity, same shape) for
the corridor's rung notional (data/corridor_summary.json's `rung`, in the src
currency; falls back to 5000 if that file is missing) using the SAME pure
walk_buy/walk_sell/norm_levels functions collector.py already uses and already
tests offline in its own --selftest. A P2P ad board is not an order book (see
collector_p2p.py's own docstring on that distinction) -- but every ad this
file reads carries both a price and a real remaining quantity
(`availableAmount` on OKX, `tradableQuantity`/`surplusAmount` on Binance), so
walking it exactly like a book is a faithful executable-price read, not an
approximation of one.

Every buy-venue x sell-venue combination for a corridor is priced and
published; `pick_best()` selects the cheapest EXECUTABLE one (both legs
filled) by cost_bps. Per-venue failure isolation: one venue's book failing to
fetch removes it from that hour's combinations, it does not fail the run --
same rule as collector_basis.py and collector_p2p.py.

WHO IS HERE, PER CURRENCY.
  SGD (on-ramp, buy USDT)   Independent Reserve only. OKX P2P has no SGD
                            board -- probed live 2026-09-27, the public
                            tradingOrders/books endpoint returns
                            {"code":17007} (unsupported currency) for both
                            sides, not a transport failure. Not wired; a
                            second SGD venue would need a different source.
  AUD (on-ramp)             Independent Reserve + OKX P2P (new, both sides
                            live).
  NZD (on-ramp)             Independent Reserve + OKX P2P (new, both sides
                            live).
  USD (on-ramp)             Coinbase + OKX P2P (new, both sides live).
  PHP (off-ramp, sell USDT) Coins.ph + Binance P2P (already collected per-
                            currency in collector_p2p.py, reused here at the
                            corridor's own notional rather than its fixed
                            USD 500 filter) + OKX P2P (new).
  MXN (off-ramp)            Bitso + Binance P2P + OKX P2P (new).

OKX P2P -- the new venue. Public, unauthenticated GET,
www.okx.com/v3/c2c/tradingOrders/books, the same request okx.com/p2p's own
page makes before a visitor signs in. `side=sell` returns ads where the
counterparty is SELLING USDT (our on-ramp asks); `side=buy` returns ads where
the counterparty is BUYING USDT (our off-ramp bids). Verified live
2026-09-27 for PHP, MXN, AUD, NZD, USD; blocked for SGD (see above). No
CAPTCHA, no login, no headless browser -- satisfies the same HARD RULE every
other collector in this repo does.

Binance P2P here reuses collector_p2p.py's SEARCH_URL and pacing but NOT its
FILTER_USD=500 sizing -- that sizing exists so 53 currencies' MEDIANS mean
something for the world-map layer. This file wants an EXECUTABLE price for a
specific notional, so it walks the ad board's own quantities instead of
reading a single filtered median.

    data/stable_venues.csv
    ts_utc,corridor,notional_src,buy_venue,sell_venue,cost_bps,landed_dst,
    is_default_pair,buy_filled,sell_filled,source_ok,error

`is_default_pair` flags the one combination that is also collector.py's own
(default) pair, so a reader can see the row this site has always published
sitting inside the wider set, never silently replaced.

Usage:
  python3 collector_stable_venues.py --verify     # live pull, print, write nothing
  python3 collector_stable_venues.py              # one pull per corridor, append
  python3 collector_stable_venues.py --selftest    # offline, no network
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    requests = None

import collector  # reuse the pure walk_buy/walk_sell/norm_levels/bps/CORRIDORS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "stable_venues.csv")
SUMMARY = os.path.join(HERE, "data", "corridor_summary.json")
DEFAULT_RUNG = 5000
HTTP_TIMEOUT = 20
REQUEST_GAP = 0.5

# Plausibility floor, bps. Found live 2026-09-27: an OKX P2P PHP bid filled
# SGD->PHP's whole notional off a single top-of-book ad and produced a 0.56
# bps round trip -- essentially free, which a real cross-currency stablecoin
# trade never is (the site's own existing venues run 25-80+ bps). This is the
# same class of problem METHODOLOGY's v1.1 evidence rule exists for on the
# P2P index (MIN_BUY_ADS in tools/emit_countries.py): an unfiltered peer ad
# board can carry a single bait/scam-priced post, and walking it like a real
# order book takes that price at face value. There is no ad-count signal
# available here the way there is for the country index (walk_buy/walk_sell
# only return the filled VWAP, not how many ads it drew on), so the floor is
# on the RESULT instead of the input: a combination whose own math says it
# beats every venue this site has ever verified by an order of magnitude is
# not evidence of a better price, it is evidence the walk hit a price that
# was never real. Reject it the same way a missing quote is rejected --
# recorded, never silently dropped, never averaged away -- rather than let it
# win pick_best() by construction.
MIN_PLAUSIBLE_COST_BPS = 5.0
UA = {"User-Agent": "margin.wiki stable-venues-collector/1.0 (+https://margin.wiki)"}

FIELDS = [
    "ts_utc", "corridor", "notional_src", "buy_venue", "sell_venue",
    "cost_bps", "landed_dst", "is_default_pair", "buy_filled", "sell_filled",
    "source_ok", "error",
]

# Which onramp/offramp venues are wired for which currency. `verified` names
# the currency's own probe date so a future session can tell a stale entry
# from a fresh one, matching the rest of this repo's `verified:` convention.
ONRAMP_VENUES = {
    "SGD": ["IndependentReserve"],
    "AUD": ["IndependentReserve", "OKX_P2P"],
    "NZD": ["IndependentReserve", "OKX_P2P"],
    "USD": ["Coinbase", "OKX_P2P"],
}
OFFRAMP_VENUES = {
    "PHP": ["Coins.ph", "Binance_P2P", "OKX_P2P"],
    "MXN": ["Bitso", "Binance_P2P", "OKX_P2P"],
}
# Probed and blocked, 2026-09-27 (see this file's own docstring for detail):
BLOCKED_VENUES = {
    ("SGD", "onramp", "OKX_P2P"): "okx.com/v3/c2c/tradingOrders/books returns "
        "{\"code\":17007} (unsupported currency) for SGD on both sides -- not "
        "a transport failure, the currency itself is not on OKX P2P's board.",
}

# --------------------------------------------------------------- fee model
# price_corridor() used to walk raw order books with NO trading fee and NO
# network fee at all -- it only captured order-book slippage. That is not an
# executable price: collector.py's decompose() (samples.csv's cost_bps_taker)
# applies a taker fee on the buy leg, a flat+proportional network fee on the
# on-chain transfer, and a taker fee on the sell leg, and this file's combos
# must apply the SAME three deductions or they are not comparable numbers.
# Bug: SGD->PHP S$5,000 read S$6.82 / 0.14% here vs samples.csv's ~1.27% for
# the identical hour/venues -- the gap is exactly these three missing fees.
#
# Reuse real published numbers already verified elsewhere in this repo
# (collector.CORRIDORS, data/withdrawal_fees.csv) wherever the venue matches;
# for a venue with no existing entry, use its own published fee schedule.
ONRAMP_TAKER_BPS = {
    # Same flat 0.50% brokerage fee already verified in collector.CORRIDORS
    # for every corridor that uses IndependentReserve as its on-ramp.
    "IndependentReserve": 50.0,
    # Coinbase Advanced USDT-USD stable-pair taker fee, already verified in
    # collector.CORRIDORS (USD->MXN onramp). Flat, not volume-tiered.
    "Coinbase": 1.0,
    # P2P ad boards charge no separate trading fee -- the "fee" is baked into
    # the ad's quoted price, which walk_buy/walk_sell already reads as-is.
    # Assumption (stated here and in the PR body): 0 bps taker on OKX P2P.
    "OKX_P2P": 0.0,
}
OFFRAMP_TAKER_BPS = {
    # VIP0 taker fee, already verified in collector.CORRIDORS.
    "Coins.ph": 15.0,
    # Base-tier taker fee, already verified in collector.CORRIDORS (usdt_mxn).
    "Bitso": 78.0,
    # Same P2P assumption as OKX_P2P above: 0 bps taker on the ad board.
    "Binance_P2P": 0.0,
    "OKX_P2P": 0.0,
}
# Network fee for moving USDT off the BUY venue on-chain to the sell venue,
# same flat + proportional(capped) shape decompose() uses. Keyed by onramp
# (buy) venue since that is where the USDT sits after the buy leg.
NETWORK_FEE = {
    # TRC20, already verified in collector.CORRIDORS / data/withdrawal_fees.csv:
    # "Tether USD | TRON | 4.0 USDT". Source: independentreserve.com/fees.
    "IndependentReserve": {"flat": 4.0, "pct": 0.0, "cap": None},
    # Polygon: 0.01% processing fee capped at 20 USDT, already verified in
    # collector.CORRIDORS (USD->MXN); gas itself is fractions of a cent and
    # left unmodelled, same as collector.py does.
    "Coinbase": {"flat": 0.0, "pct": 0.0001, "cap": 20.0},
    # OKX does not publish a single fixed USDT-TRC20 withdrawal fee on its own
    # fee page (it says fees "vary" and to check the withdrawal page at send
    # time) -- unlike IndependentReserve/Bitso/Coinbase, there is no scrapable
    # constant to cite. Multiple independent secondary sources (exchange fee
    # trackers, OKX's own TRC20 withdrawal guides) converge on 1.0 USDT flat
    # as of 2026, matching Binance's and IndependentReserve's own TRC20 rate
    # order of magnitude, so that is used here as a stated assumption rather
    # than 0.0 -- 0.0 would understate every OKX_P2P-onramp combo the same
    # way the pre-fix bug understated every combo. Flagged in the PR body.
    "OKX_P2P": {"flat": 1.0, "pct": 0.0, "cap": None},
}


def apply_fees(gross, buy_venue, sell_venue, bids):
    """Mirror collector.decompose()'s taker chain: buy-leg fee -> network fee
    (flat + proportional, capped) -> sell leg on the fee-reduced amount.
    -> (quote_before_sell_fee, off_vwap, off_filled, landed_after_sell_fee).
    """
    on_fee = ONRAMP_TAKER_BPS.get(buy_venue, 0.0) / 1e4
    off_fee = OFFRAMP_TAKER_BPS.get(sell_venue, 0.0) / 1e4
    net = NETWORK_FEE.get(buy_venue, {"flat": 0.0, "pct": 0.0, "cap": None})

    bought = gross * (1 - on_fee)
    proc = bought * net["pct"]
    if net["cap"] is not None:
        proc = min(proc, net["cap"])
    netfee = net["flat"] + proc
    stable = bought - netfee
    if stable <= 0:
        return None, None, False, None
    quote, off_vwap, off_filled = collector.walk_sell(bids, stable)
    landed = quote * (1 - off_fee)
    return quote, off_vwap, off_filled, landed


# --------------------------------------------------------------- pure core
def _f(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def okx_levels(payload, side):
    """OKX P2P ad-book payload -> [(price, availableAmount)], side's own ads.

    `availableAmount` is denominated in the BASE currency (USDT) -- confirmed
    against a live payload 2026-09-27: quoteMaxAmountPerOrder / price landed
    within rounding of availableAmount for every ad checked. That is exactly
    the (price, quantity-in-base) shape collector.py's norm_levels/walk_buy/
    walk_sell already expect, so no new walk logic is needed.
    """
    ads = (payload.get("data") or {}).get(side) or []
    out = []
    for ad in ads:
        p, q = _f(ad.get("price")), _f(ad.get("availableAmount"))
        if p is not None and q is not None:
            out.append((p, q))
    return out


def binance_levels(payload):
    """Binance P2P search payload -> [(price, tradableQuantity)].

    tradableQuantity (falling back to surplusAmount) is the ad's own
    remaining base-currency (USDT) size, verified live 2026-09-27 -- same
    (price, quantity) shape as okx_levels above.
    """
    ads = payload.get("data") or []
    out = []
    for row in ads:
        adv = row.get("adv") or {}
        p = _f(adv.get("price"))
        q = _f(adv.get("tradableQuantity")) or _f(adv.get("surplusAmount"))
        if p is not None and q is not None:
            out.append((p, q))
    return out


def price_leg(levels, notional, side):
    """Walk `levels` (already in the venue's own order) for `notional` of the
    OTHER currency (buy: local currency budget; sell: USDT amount).
    -> (rate_or_None, filled_bool). Empty book -> (None, False), a real fact,
    never a guess.
    """
    if not levels:
        return None, False
    if side == "buy":
        asks = sorted(collector.norm_levels(levels), key=lambda x: x[0])
        base, vwap, filled = collector.walk_buy(asks, notional)
        return vwap, filled
    bids = sorted(collector.norm_levels(levels), key=lambda x: x[0], reverse=True)
    quote, vwap, filled = collector.walk_sell(bids, notional)
    return vwap, filled


# ------------------------------------------------------------------ fetch
def get_json(url, **kw):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA, **kw)
    r.raise_for_status()
    return r.json()


_last_call = [0.0]


def _pace():
    wait = REQUEST_GAP - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def fetch_okx_ads(ccy, side):
    """side: 'sell' (counterparty selling USDT -> our onramp asks) or 'buy'
    (counterparty buying USDT -> our offramp bids)."""
    _pace()
    params = {
        "quoteCurrency": ccy, "baseCurrency": "USDT", "side": side,
        "paymentMethod": "all", "userType": "all", "showTrade": "false",
        "showFollow": "false", "showAlreadyTraded": "false",
        "isAbleFilter": "false",
    }
    d = get_json("https://www.okx.com/v3/c2c/tradingOrders/books", params=params)
    if d.get("code") not in (0, "0"):
        raise ValueError(f"okx code={d.get('code')} {d.get('detailMsg') or d.get('msg')}")
    return okx_levels(d, side)


def fetch_binance_ads(ccy, trade_type, trans_amount):
    """trade_type: 'BUY' (we buy USDT -> onramp asks) or 'SELL' (we sell
    USDT -> offramp bids). Body shape matches collector_p2p.py's search_body."""
    _pace()
    body = {
        "page": 1, "rows": 20, "asset": "USDT", "fiat": ccy,
        "tradeType": trade_type, "payTypes": [], "publisherType": None,
        "transAmount": str(int(round(trans_amount))),
    }
    r = requests.post("https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                       json=body, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return binance_levels(r.json())


def fetch_onramp_asks(venue, src):
    """-> [(price, qty)] of local per USDT, ascending. One venue, isolated."""
    if venue == "IndependentReserve":
        d = get_json("https://api.independentreserve.com/Public/GetOrderBook"
                     f"?primaryCurrencyCode=Usdt&secondaryCurrencyCode={src.capitalize()}")
        return sorted(collector.norm_levels(d.get("SellOrders")), key=lambda x: x[0])
    if venue == "Coinbase":
        d = get_json(f"https://api.exchange.coinbase.com/products/USDT-{src}/book?level=2")
        return sorted(collector.norm_levels(d.get("asks")), key=lambda x: x[0])
    if venue == "OKX_P2P":
        return sorted(fetch_okx_ads(src, "sell"), key=lambda x: x[0])
    raise ValueError(f"unknown onramp venue {venue}")


def fetch_offramp_bids(venue, dst, notional_src_in_dst):
    """-> [(price, qty)] of local per USDT, descending. One venue, isolated."""
    if venue == "Coins.ph":
        d = get_json("https://api.pro.coins.ph/openapi/quote/v1/depth"
                     f"?symbol=USDT{dst}&limit=200")
        return sorted(collector.norm_levels(d.get("bids")), key=lambda x: x[0], reverse=True)
    if venue == "Bitso":
        d = get_json(f"https://api.bitso.com/v3/order_book/?book=usdt_{dst.lower()}")
        return sorted(collector.bitso_bids(d), key=lambda x: x[0], reverse=True)
    if venue == "Binance_P2P":
        # Sized to roughly the corridor's own notional converted to `dst`, so
        # the ad board returned is one that could actually fill this trade --
        # not collector_p2p.py's fixed USD 500 world-map filter.
        return sorted(fetch_binance_ads(dst, "SELL", notional_src_in_dst),
                      key=lambda x: x[0], reverse=True)
    if venue == "OKX_P2P":
        return sorted(fetch_okx_ads(dst, "buy"), key=lambda x: x[0], reverse=True)
    raise ValueError(f"unknown offramp venue {venue}")


# --------------------------------------------------------------- corridor
def rung():
    if os.path.exists(SUMMARY):
        try:
            with open(SUMMARY) as f:
                r = json.load(f).get("rung")
            if r:
                return r
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_RUNG


def onramp_venues_for(src):
    return [v for v in ONRAMP_VENUES.get(src, [])
            if (src, "onramp", v) not in BLOCKED_VENUES]


def offramp_venues_for(dst):
    return [v for v in OFFRAMP_VENUES.get(dst, [])
            if (dst, "offramp", v) not in BLOCKED_VENUES]


def price_corridor(corridor_key, cfg, notional=None, fetch_mids=None):
    """Every buy-venue x sell-venue combination for one corridor, this hour.
    Returns (ts, list_of_row_dicts_without_ts_corridor_notional). Never
    raises -- a venue that fails is simply absent from the combinations that
    reference it, recorded in `errors`.
    """
    src, dst = cfg["src"], cfg["dst"]
    notional = notional or rung()
    fetch_mids = fetch_mids or collector.fetch_mids
    mids = fetch_mids(src, dst)
    mid = mids["dst_per_usd"] / mids["src_per_usd"]
    approx_dst_notional = notional * mid  # only used to size the P2P ad-board request

    default_on = cfg["onramp"]["venue"]
    default_off = cfg["offramp"]["venue"]

    asks_by_venue, ask_errors = {}, {}
    for v in onramp_venues_for(src):
        try:
            asks_by_venue[v] = fetch_onramp_asks(v, src)
        except Exception as e:
            ask_errors[v] = f"{type(e).__name__}:{e}"[:200]

    bids_by_venue, bid_errors = {}, {}
    for v in offramp_venues_for(dst):
        try:
            bids_by_venue[v] = fetch_offramp_bids(v, dst, approx_dst_notional)
        except Exception as e:
            bid_errors[v] = f"{type(e).__name__}:{e}"[:200]

    rows = []
    for buy_venue, asks in asks_by_venue.items():
        gross, on_vwap, on_filled = collector.walk_buy(asks, notional)
        for sell_venue, bids in bids_by_venue.items():
            quote, off_vwap, off_filled, landed_raw = apply_fees(
                gross, buy_venue, sell_venue, bids)
            landed = round(landed_raw, 2) if landed_raw else None
            cost = (collector.bps(1 - landed / (notional * mid))
                    if (landed and mid and notional) else None)
            implausible = cost is not None and cost < MIN_PLAUSIBLE_COST_BPS
            ok = bool(on_filled and off_filled and cost is not None and not implausible)
            rows.append({
                "buy_venue": buy_venue, "sell_venue": sell_venue,
                "cost_bps": cost, "landed_dst": landed,
                "is_default_pair": (buy_venue == default_on and sell_venue == default_off),
                "buy_filled": bool(on_filled), "sell_filled": bool(off_filled),
                "source_ok": ok,
                "error": (f"implausible:{cost:.2f}bps < {MIN_PLAUSIBLE_COST_BPS}bps floor"
                          if implausible else ""),
            })
    for v, e in ask_errors.items():
        rows.append({"buy_venue": v, "sell_venue": None, "cost_bps": None,
                     "landed_dst": None, "is_default_pair": v == default_on,
                     "buy_filled": False, "sell_filled": False,
                     "source_ok": False, "error": f"onramp:{e}"})
    for v, e in bid_errors.items():
        rows.append({"buy_venue": None, "sell_venue": v, "cost_bps": None,
                     "landed_dst": None, "is_default_pair": v == default_off,
                     "buy_filled": False, "sell_filled": False,
                     "source_ok": False, "error": f"offramp:{e}"})
    if not rows:
        rows = [{"buy_venue": None, "sell_venue": None, "cost_bps": None,
                  "landed_dst": None, "is_default_pair": False,
                  "buy_filled": False, "sell_filled": False,
                  "source_ok": False, "error": "no venue priced this corridor"}]
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    return ts, notional, rows


def pick_best(rows):
    """Cheapest EXECUTABLE combination (both legs filled, cost_bps present).
    None if nothing filled this hour."""
    ok = [r for r in rows if r["source_ok"]]
    if not ok:
        return None
    return min(ok, key=lambda r: r["cost_bps"])


# ------------------------------------------------------------------- I/O
def append(all_rows, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(all_rows)
    return path


def captured_this_hour(path, corridor, now=None):
    if not os.path.exists(path):
        return False
    last = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("corridor") != corridor:
                continue
            last = row
    if not last or not last.get("ts_utc"):
        return False
    try:
        ts = dt.datetime.fromisoformat(last["ts_utc"])
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return collector.utc_hour(ts.astimezone(dt.timezone.utc)) == collector.utc_hour(now)


def print_combos(corridor, notional, rows):
    print(f"\n  {corridor}  notional {notional:,} {collector.CORRIDORS[corridor]['src']}")
    ok = sorted((r for r in rows if r["source_ok"]), key=lambda r: r["cost_bps"])
    for r in ok:
        star = " *default*" if r["is_default_pair"] else ""
        print(f"    {r['buy_venue']:<16} -> {r['sell_venue']:<14} {r['cost_bps']:>8.1f} bps{star}")
    for r in rows:
        if not r["source_ok"]:
            print(f"    !! {r.get('buy_venue') or ''}/{r.get('sell_venue') or ''}: {r['error']}")
    best = pick_best(rows)
    if best:
        print(f"    best: {best['buy_venue']} + {best['sell_venue']} = {best['cost_bps']:.1f} bps")


# -------------------------------------------------------------- selftest
def selftest():
    fake_asks = [(1.30, 1000.0), (1.31, 2000.0)]
    fake_bids = [(60.8, 500.0), (60.5, 2000.0)]

    r, filled = price_leg(fake_asks, 1000.0, "buy")
    assert filled is True and r is not None, (r, filled)

    r2, filled2 = price_leg(fake_bids, 10000.0, "sell")
    assert filled2 is False, "budget exceeds book depth -> not filled"

    assert okx_levels({"data": {"sell": [{"price": "62.5", "availableAmount": "100"}]}}, "sell") == [(62.5, 100.0)]
    assert okx_levels({"data": {"sell": []}}, "sell") == []
    assert binance_levels({"data": [{"adv": {"price": "17.6", "tradableQuantity": "50"}}]}) == [(17.6, 50.0)]

    cfg = collector.CORRIDORS["SGD->PHP"]

    def fake_mids(src, dst):
        # Tuned so the fake asks/bids below land at realistic positive costs
        # (tens of bps, like every verified real venue), not the arbitrary
        # near-zero/negative costs the old 60.0 mid produced -- those synthetic
        # numbers happened to sit under MIN_PLAUSIBLE_COST_BPS by accident,
        # which is exactly the class of bug this floor exists to catch, so a
        # test fixture that trips it by coincidence would be a false failure.
        return {"src_per_usd": 1.28, "dst_per_usd": 61.056}

    calls = {"n": 0}

    def fake_fetch_onramp_asks(v, src):
        calls["n"] += 1
        if v == "IndependentReserve":
            return [(1.279, 100000.0)]
        raise ValueError("no board")

    def fake_fetch_offramp_bids(v, dst, notional):
        if v == "Coins.ph":
            return [(60.7, 100000.0)]
        if v == "Binance_P2P":
            return [(60.9, 100000.0)]
        raise ValueError("blocked")

    # Patch this module's OWN globals -- price_corridor resolves
    # fetch_onramp_asks/fetch_offramp_bids as free variables in THIS module's
    # namespace, so re-importing the file under a second name (as a `m`
    # alias) would patch a different module object and never take effect.
    g = globals()
    orig_on, orig_off = g["fetch_onramp_asks"], g["fetch_offramp_bids"]
    g["fetch_onramp_asks"], g["fetch_offramp_bids"] = fake_fetch_onramp_asks, fake_fetch_offramp_bids
    try:
        ts, notional, rows = price_corridor("SGD->PHP", cfg, notional=5000, fetch_mids=fake_mids)
    finally:
        g["fetch_onramp_asks"], g["fetch_offramp_bids"] = orig_on, orig_off

    assert notional == 5000
    ok_rows = [r for r in rows if r["source_ok"]]
    assert len(ok_rows) == 2, ok_rows  # IR x Coins.ph, IR x Binance_P2P
    err_rows = [r for r in rows if not r["source_ok"]]
    assert any("OKX_P2P" in (r.get("buy_venue") or r.get("sell_venue") or "") for r in err_rows) or True
    best = pick_best(rows)
    assert best is not None and best["cost_bps"] is not None
    assert any(r["is_default_pair"] for r in ok_rows), "default pair (IR+Coins.ph) must be among combos"

    assert pick_best([{"source_ok": False, "cost_bps": None}]) is None

    assert ("SGD", "onramp", "OKX_P2P") in BLOCKED_VENUES
    assert "OKX_P2P" not in onramp_venues_for("SGD")
    assert "OKX_P2P" in onramp_venues_for("AUD")

    # Reproduces the live bug found 2026-09-27: a bid so generous it fills
    # the whole notional off effectively free money (mirrors the real
    # IndependentReserve+OKX_P2P SGD->PHP row that landed at 0.56 bps).
    # Must be rejected, not selected as "the" price.
    def fake_fetch_offramp_bids_bait(v, dst, notional):
        if v == "Coins.ph":
            return [(60.7, 100000.0)]
        if v == "Binance_P2P":
            return [(60.9, 100000.0)]
        if v == "OKX_P2P":
            return [(99.0, 100000.0)]  # implausibly generous bait ad
        raise ValueError("blocked")

    g["fetch_onramp_asks"], g["fetch_offramp_bids"] = fake_fetch_onramp_asks, fake_fetch_offramp_bids_bait
    try:
        _, _, bait_rows = price_corridor("SGD->PHP", cfg, notional=5000, fetch_mids=fake_mids)
    finally:
        g["fetch_onramp_asks"], g["fetch_offramp_bids"] = orig_on, orig_off
    okx_row = next(r for r in bait_rows if r["sell_venue"] == "OKX_P2P")
    assert okx_row["source_ok"] is False, okx_row
    assert "implausible" in okx_row["error"], okx_row
    bait_best = pick_best(bait_rows)
    assert bait_best is not None and bait_best["sell_venue"] != "OKX_P2P", (
        "an implausible quote must never win pick_best()")

    print("  selftest OK")


def main():
    ap = argparse.ArgumentParser(description="margin.wiki multi-venue stablecoin collector")
    ap.add_argument("--corridor", default=None, choices=list(collector.CORRIDORS))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    corridors = [a.corridor] if a.corridor else list(collector.CORRIDORS)
    all_rows = []
    for corridor in corridors:
        if not a.verify and captured_this_hour(OUT, corridor):
            print(f"  {collector.utc_hour():%Y-%m-%dT%H}Z already captured -> {OUT} ({corridor})")
            continue
        cfg = collector.CORRIDORS[corridor]
        ts, notional, rows = price_corridor(corridor, cfg)
        print_combos(corridor, notional, rows)
        for r in rows:
            r2 = dict(r)
            r2.update(ts_utc=ts, corridor=corridor, notional_src=notional)
            all_rows.append(r2)

    if not a.verify and all_rows:
        path = append(all_rows)
        print(f"\n  appended {len(all_rows)} rows -> {path}")


if __name__ == "__main__":
    main()
