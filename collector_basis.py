#!/usr/bin/env python3
"""
margin.wiki basis collector -- the WIDE layer.

One ticker call per venue per hour: where does USDT trade against the official
USD FX mid, expressed as basis in bps? No fees, no order-book walk, no fee
verification -- this is a pure market price, and it is the signal the world map
is coloured by. See HANDOFF v2 ("Architecture decision: two layers").

    basis_bps = (usdt_mid_in_local / fx_mid_local_per_usd - 1) * 10_000

Positive basis = USDT trades RICH to the official dollar (capital wants out;
Turkey, Argentina). ~0 = a calibrated, open market (Singapore, the anchor).

Wide-layer rules -- deliberately different from the corridor collector:
  - Per-venue failure isolation. One venue erroring writes a row with
    source_ok=False and the error string; it does NOT kill the run.
  - The run exits non-zero ONLY on a total blackout (every venue failed, or
    the shared FX snapshot failed). A partial pull is a success with holes,
    and the holes are visible as source_ok=False rows -- never absent.
  - FX mid is snapshotted ONCE per run and shared across venues.

The registry is the extension point: add a venue = add one dict. New venues
(BTCTurk, Upbit, Indodax, Bitkub, Bitso, CriptoYa) land next session; today
only the two existing corridor legs are registered, as proof the shape works.

Usage:
  python3 collector_basis.py --verify     # one live pull, print, write nothing
  python3 collector_basis.py              # one pull, append data/basis.csv
  python3 collector_basis.py --selftest   # offline, mocked venues + a failure
"""

import argparse
import collections
import csv
import datetime as dt
import json
import os
import statistics
import sys

try:
    import requests
except ImportError:
    requests = None

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki basis-collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
BASIS = os.path.join(HERE, "data", "basis.csv")
STABLE = os.path.join(HERE, "data", "stable_spread.csv")
FX_URL = "https://open.er-api.com/v6/latest/USD"

FIELDS = [
    "ts_utc", "venue", "ccy",
    "usdt_bid", "usdt_ask", "usdt_mid",
    "fx_mid_per_usd", "basis_bps",
    # source: which feed the quote came from. "criptoya" marks the aggregated,
    # snapshot-only (no-backfill) venues so the map can flag them; the direct
    # venues carry their own slug. History-backed = also present in
    # data/basis_history.csv.
    "source",
    "source_ok", "error",
]

# The USDT-vs-USDC layer. Its own file and its own frozen schema: basis.csv has
# one price per row and adding a second stablecoin to it would either mean a new
# column on a frozen schema or a second row that looks like a second venue.
STABLE_FIELDS = [
    "ts_utc", "venue", "ccy", "usdt_mid", "usdc_mid", "spread_bps",
    "source_ok", "error",
]


# ------------------------------------------------------------- pure core
def _f(x):
    """Coerce to a positive float, or None. Venues return prices as strings."""
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def mid_of(bid, ask, last):
    """Best available mid: prefer bid/ask midpoint, fall back to last/one side."""
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    if last is not None:
        return last
    return ask if ask is not None else bid


def basis_bps(usdt_mid, fx_mid):
    """USDT premium/discount to the official USD mid, in bps. None if either missing."""
    if not usdt_mid or not fx_mid:
        return None
    return round((usdt_mid / fx_mid - 1) * 1e4, 2)


# --------------------------------------------------------- venue parsers
# Each parser maps a venue's ticker payload to (bid, ask, last) in LOCAL per
# USDT. Return None for any field the venue omits; mid_of() copes.
def parse_independent_reserve(d):
    # GetMarketSummary: dict with Current{Highest,Lowest}{Bid,Offer}Price + LastPrice.
    return (_f(d.get("CurrentHighestBidPrice")),
            _f(d.get("CurrentLowestOfferPrice")),
            _f(d.get("LastPrice")))


def parse_coins_pro(d):
    # openapi bookTicker: {"symbol","bidPrice","bidQty","askPrice","askQty"}.
    return (_f(d.get("bidPrice")), _f(d.get("askPrice")), None)


def parse_btcturk(d):
    # v2/ticker: {"data":[{"bid","ask","last",...}], "success":bool}. Numeric.
    row = (d.get("data") or [{}])[0]
    return (_f(row.get("bid")), _f(row.get("ask")), _f(row.get("last")))


def parse_upbit(d):
    # v1/ticker: [{"market":"KRW-USDT","trade_price":...}]. No bid/ask -> last only.
    # KRW is the QUOTE currency, so trade_price is already won per USDT.
    row = d[0] if isinstance(d, list) and d else {}
    return (None, None, _f(row.get("trade_price")))


def parse_indodax(d):
    # api/{pair}/ticker: {"ticker":{"buy","sell","last",...}}. String-priced.
    t = d.get("ticker") or {}
    return (_f(t.get("buy")), _f(t.get("sell")), _f(t.get("last")))


def parse_bitkub(d, sym="THB_USDT"):
    # market/ticker: all pairs keyed by "THB_USDT" -> {"highestBid","lowestAsk","last"}.
    # `sym` because the same payload also carries THB_USDC.
    t = d.get(sym) or {}
    return (_f(t.get("highestBid")), _f(t.get("lowestAsk")), _f(t.get("last")))


def parse_bitso(d):
    # v3/ticker: {"success":bool,"payload":{"bid","ask","last",...}}. String-priced.
    p = d.get("payload") or {}
    return (_f(p.get("bid")), _f(p.get("ask")), _f(p.get("last")))


def parse_criptoya(d):
    # General endpoint: {exchange: {"ask","bid","totalAsk","totalBid","time"}}.
    # Returns the MEDIAN raw bid and MEDIAN raw ask across every listed exchange
    # (robust to one stale/outlier venue). Raw, NOT totalBid/totalAsk -- those
    # bake in fees; we want the market price. The registry sets mid_rule="bid"
    # for these venues, so build_rows() takes the median bid as the
    # representative price: CriptoYa aggregates brokers whose ASK carries ~100
    # bps of retail markup, which inflates a naive midpoint. See METHODOLOGY.
    if not isinstance(d, dict):
        return (None, None, None)
    bids = [b for b in (_f(v.get("bid")) for v in d.values()
                        if isinstance(v, dict)) if b]
    asks = [a for a in (_f(v.get("ask")) for v in d.values()
                        if isinstance(v, dict)) if a]
    return (statistics.median(bids) if bids else None,
            statistics.median(asks) if asks else None, None)


def parse_bithumb(d):
    # public/orderbook/USDT_KRW?count=1: {"status":"0000","data":{"bids":[{"price"}],
    # "asks":[{"price"}]}}. The /public/ticker endpoint has no bid/ask at all --
    # only closing_price -- so the order book is the honest source here.
    data = d.get("data") or {}
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    bid = _f(bids[0].get("price")) if bids and isinstance(bids[0], dict) else None
    ask = _f(asks[0].get("price")) if asks and isinstance(asks[0], dict) else None
    return (bid, ask, None)


def parse_coinone(d):
    # public/v2/ticker_new/KRW/USDT: {"tickers":[{"best_bids":[{"price"}],
    # "best_asks":[{"price"}],"last"}]}. KRW is the quote, so prices are won/USDT.
    t = (d.get("tickers") or [{}])[0]
    if not isinstance(t, dict):
        return (None, None, None)
    bids = t.get("best_bids") or []
    asks = t.get("best_asks") or []
    bid = _f(bids[0].get("price")) if bids and isinstance(bids[0], dict) else None
    ask = _f(asks[0].get("price")) if asks and isinstance(asks[0], dict) else None
    return (bid, ask, _f(t.get("last")))


def parse_paribu(d, key="USDT_TL"):
    # /ticker: every pair in one payload, keyed "USDT_TL" (Paribu says TL, not
    # TRY). {"lowestAsk","highestBid","last"}. Numeric. USDC_TL is in the same
    # payload, hence `key`.
    t = d.get(key) or {}
    return (_f(t.get("highestBid")), _f(t.get("lowestAsk")), _f(t.get("last")))


def parse_foxbit(d, sym="usdtbrl"):
    # rest/v3/markets/ticker/24hr: every market in one list. The `symbols` query
    # param is ignored by the API (verified 2026-09-02 -- it returns btcbrl
    # first regardless), so filter here rather than trusting the URL.
    for row in (d.get("data") or []):
        if isinstance(row, dict) and row.get("market_symbol") == sym:
            best = row.get("best") or {}
            bid = (best.get("bid") or {}).get("price")
            ask = (best.get("ask") or {}).get("price")
            last = (row.get("last_trade") or {}).get("price")
            return (_f(bid), _f(ask), _f(last))
    return (None, None, None)


def parse_mercadobitcoin(d):
    # api/v4/tickers?symbols=USDT-BRL: [{"pair":"USDT-BRL","buy","sell","last"}].
    # buy/sell are the book's best bid/ask. String-priced.
    row = d[0] if isinstance(d, list) and d else {}
    if not isinstance(row, dict):
        return (None, None, None)
    return (_f(row.get("buy")), _f(row.get("sell")), _f(row.get("last")))


def parse_pintu(d, pair="usdt/idr"):
    # v2/trade/price-changes: {"payload":[{"pair":"usdt/idr","latestPrice"}]}.
    # Last price only -- Pintu publishes no public book, so mid_of() falls back
    # to last and usdt_bid/usdt_ask stay empty. That is a real limitation of the
    # source, recorded as blank cells rather than papered over.
    for row in (d.get("payload") or []):
        if isinstance(row, dict) and row.get("pair") == pair:
            return (None, None, _f(row.get("latestPrice")))
    return (None, None, None)


def expand_criptoya(d):
    """CriptoYa's payload is many exchanges at once -> one row each.

    The aggregate row (median across exchanges, see parse_criptoya) is still
    written and still keys the existing history. This is the per-exchange
    detail underneath it, so a country whose only source is CriptoYa can have a
    median across real venues instead of a median presented as a venue.

    P2P books are dropped. They are a different market with a different
    mechanism -- an advertised price with counterparty risk and no matching
    engine -- and they are their own piece of work (ROADMAP, P2P layer). Mixing
    them into a spot median silently would be the kind of quiet blend this repo
    exists to avoid. That also keeps Binance out, per the invariant.

    -> [(exchange_name, bid, ask, last)], sorted, empty on a malformed payload.
    """
    if not isinstance(d, dict):
        return []
    out = []
    for name, v in sorted(d.items()):
        if not isinstance(v, dict) or "p2p" in name.lower():
            continue
        bid, ask = _f(v.get("bid")), _f(v.get("ask"))
        if bid is None and ask is None:
            continue
        out.append((name, bid, ask, None))
    return out


# ------------------------------------------------------------- registry
# name       : row label, must be stable (it keys history)
# fiat_ccy   : ISO code, indexes the shared FX snapshot
# ticker_url : public, no-auth endpoint
# parse_fn   : payload -> (bid, ask, last) local per USDT
# candles_fn : historical backfill; None until wired (next session)
# enabled    : drop a venue without deleting its config
VENUES = [
    {
        "name": "IndependentReserve",
        "fiat_ccy": "SGD",
        "ticker_url": ("https://api.independentreserve.com/Public/GetMarketSummary"
                       "?primaryCurrencyCode=Usdt&secondaryCurrencyCode=Sgd"),
        "parse_fn": parse_independent_reserve,
        "candles_fn": None,
        "usdc_url": ("https://api.independentreserve.com/Public/GetMarketSummary"
                     "?primaryCurrencyCode=Usdc&secondaryCurrencyCode=Sgd"),
        "enabled": True,
    },
    {
        "name": "Coins.ph",
        "fiat_ccy": "PHP",
        # api.pro.coins.ph -- `api.coins.ph` is NXDOMAIN (killed v1 for 34 days).
        "ticker_url": ("https://api.pro.coins.ph/openapi/quote/v1/ticker/bookTicker"
                       "?symbol=USDTPHP"),
        "parse_fn": parse_coins_pro,
        "candles_fn": None,
        "usdc_url": ("https://api.pro.coins.ph/openapi/quote/v1/ticker/bookTicker"
                     "?symbol=USDCPHP"),
        "enabled": True,
    },
    # --- item 3: five new venues (endpoints verified live 2026-08-10). Each is
    # non-Binance on purpose: Binance 451s the US GitHub runners. Any venue that
    # still blocks the runner gets enabled=False + a note here -- never proxied.
    {
        "name": "BTCTurk",
        "fiat_ccy": "TRY",
        "ticker_url": "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY",
        "parse_fn": parse_btcturk,
        "candles_fn": None,
        "usdc_url": "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDCTRY",
        "enabled": True,
    },
    {
        "name": "Upbit",
        "fiat_ccy": "KRW",
        "ticker_url": "https://api.upbit.com/v1/ticker?markets=KRW-USDT",
        "parse_fn": parse_upbit,
        "candles_fn": None,
        "usdc_url": "https://api.upbit.com/v1/ticker?markets=KRW-USDC",
        "enabled": True,
    },
    {
        "name": "Indodax",
        "fiat_ccy": "IDR",
        "ticker_url": "https://indodax.com/api/usdt_idr/ticker",
        "parse_fn": parse_indodax,
        "candles_fn": None,
        "usdc_url": "https://indodax.com/api/usdc_idr/ticker",
        "enabled": True,
    },
    {
        "name": "Bitkub",
        "fiat_ccy": "THB",
        "ticker_url": "https://api.bitkub.com/api/market/ticker",
        "parse_fn": parse_bitkub,
        "candles_fn": None,
        # Same payload as USDT -- one fetch, two pairs.
        "usdc_url": "https://api.bitkub.com/api/market/ticker",
        "usdc_parse_fn": lambda d: parse_bitkub(d, "THB_USDC"),
        "enabled": True,
    },
    {
        "name": "Bitso",
        "fiat_ccy": "MXN",
        # production host (api.bitso.com, not stage); 60 req/min public limit.
        "ticker_url": "https://api.bitso.com/api/v3/ticker?book=usdt_mxn",
        "parse_fn": parse_bitso,
        "candles_fn": None,
        "enabled": True,
    },
    # --- 2026-09-02: a second venue per currency, so a country's headline is a
    # median across venues rather than one venue's opinion. Every endpoint below
    # was called from a US GitHub runner (the environment production runs in,
    # not a laptop) on 2026-09-02 and returned a real USDT quote. Candidates
    # that did NOT are listed under "not added" beneath the registry, with the
    # status code, rather than being left as an unexplained absence.
    {
        "name": "Bithumb",
        "fiat_ccy": "KRW",
        # Order book, not /public/ticker: the ticker endpoint publishes no
        # bid/ask at all, only closing_price.
        "ticker_url": "https://api.bithumb.com/public/orderbook/USDT_KRW?count=1",
        "parse_fn": parse_bithumb,
        "candles_fn": None,
        "usdc_url": "https://api.bithumb.com/public/orderbook/USDC_KRW?count=1",
        "enabled": True,
    },
    {
        "name": "Coinone",
        "fiat_ccy": "KRW",
        "ticker_url": "https://api.coinone.co.kr/public/v2/ticker_new/KRW/USDT",
        "parse_fn": parse_coinone,
        "candles_fn": None,
        "usdc_url": "https://api.coinone.co.kr/public/v2/ticker_new/KRW/USDC",
        "enabled": True,
    },
    {
        "name": "Paribu",
        "fiat_ccy": "TRY",
        "ticker_url": "https://www.paribu.com/ticker",
        "parse_fn": parse_paribu,
        "candles_fn": None,
        "usdc_url": "https://www.paribu.com/ticker",
        "usdc_parse_fn": lambda d: parse_paribu(d, "USDC_TL"),
        "enabled": True,
    },
    {
        "name": "Pintu",
        "fiat_ccy": "IDR",
        # Last price only -- no public book. usdt_bid/usdt_ask stay empty.
        "ticker_url": "https://api.pintu.co.id/v2/trade/price-changes",
        "parse_fn": parse_pintu,
        "candles_fn": None,
        "usdc_url": "https://api.pintu.co.id/v2/trade/price-changes",
        "usdc_parse_fn": lambda d: parse_pintu(d, "usdc/idr"),
        "enabled": True,
    },
    {
        "name": "Foxbit",
        "fiat_ccy": "BRL",
        "ticker_url": "https://api.foxbit.com.br/rest/v3/markets/ticker/24hr",
        "parse_fn": parse_foxbit,
        "candles_fn": None,
        "usdc_url": "https://api.foxbit.com.br/rest/v3/markets/ticker/24hr",
        "usdc_parse_fn": lambda d: parse_foxbit(d, "usdcbrl"),
        "enabled": True,
    },
    {
        "name": "MercadoBitcoin",
        "fiat_ccy": "BRL",
        # Cloudflare 1009s this from some countries (it did from a laptop in
        # Asia); it answers 200 from the US runner, which is where it runs.
        "ticker_url": "https://api.mercadobitcoin.net/api/v4/tickers?symbols=USDT-BRL",
        "parse_fn": parse_mercadobitcoin,
        "candles_fn": None,
        "usdc_url": "https://api.mercadobitcoin.net/api/v4/tickers?symbols=USDC-BRL",
        "enabled": True,
    },
    # --- item 5: CriptoYa aggregator. ONE integration = the LatAm
    # parallel-dollar map. Snapshot-only (no candle history), so source is
    # "criptoya" and the map marks these venues as no-history. General endpoint;
    # the quote taken is the median across listed exchanges (see parse_criptoya).
    # For ARS/VES the er-api comparator is the OFFICIAL rate, so basis here IS
    # the parallel-dollar premium -- the whole point. Attribute CriptoYa on site.
    # ARS and VES have no direct venue at all, so their aggregate row was also
    # their only row. expand_fn writes one extra row per exchange CriptoYa
    # lists (P2P excluded), which is what lets a median be a median. The
    # aggregate row is kept unchanged -- it keys 2024-onward history and the
    # backfill -- and is excluded from the median by name.
    {
        "name": "CriptoYa (ARS)", "fiat_ccy": "ARS",
        "ticker_url": "https://criptoya.com/api/USDT/ARS/1",
        "parse_fn": parse_criptoya, "candles_fn": None, "enabled": True,
        "source": "criptoya", "mid_rule": "bid", "expand_fn": expand_criptoya,
    },
    {
        "name": "CriptoYa (VES)", "fiat_ccy": "VES",
        "ticker_url": "https://criptoya.com/api/USDT/VES/1",
        "parse_fn": parse_criptoya, "candles_fn": None, "enabled": True,
        "source": "criptoya", "mid_rule": "bid", "expand_fn": expand_criptoya,
    },
    {
        "name": "CriptoYa (BRL)", "fiat_ccy": "BRL",
        "ticker_url": "https://criptoya.com/api/USDT/BRL/1",
        "parse_fn": parse_criptoya, "candles_fn": None, "enabled": True,
        "source": "criptoya", "mid_rule": "bid",
    },
]

# Candidates called and REJECTED, 2026-09-02, all from a US GitHub runner. Kept
# here because "why is there only one venue for the Philippines" is a question
# the site now has to answer, and an empty list is not an answer.
#
#   PDAX (PHP)            403 {"message":"Forbidden"} on every path tried
#                         (/trading-pairs, /markets, /products, /public/ticker,
#                         /v1/trading-pairs). No public ticker exists.
#   Coinhako (SGD)        403, Cloudflare interstitial. No public API.
#   Orbix (THB)           no public ticker endpoint found to call at all.
#   Binance TH (THB)      reachable (200), but -1121 "Invalid symbol" for
#                         USDTTHB: it has no USDT/THB book to quote. Its own
#                         product list is USDC-quoted.
#   Binance TR (TRY)      451. Binance MX / binance.com (MXN, TRY): 451,
#                         "restricted location". Unchanged since 2026-08-10 and
#                         the reason for the no-Binance invariant.
#   Tokocrypto (IDR)      451 from the runner; separately, its symbol list has
#                         no USDT_IDR pair -- IDR pairs there are BTC/ETH/etc.
#   Reku (IDR)            404, no public tickers endpoint at the documented path.
#
# So SGD, PHP, THB and MXN still have exactly one venue each. The site says so
# rather than showing a one-venue median, and no number is invented to fill the
# gap.

# Aggregate rows: a median across exchanges, not a venue. They are written (they
# key the pre-2026-09 history) but must never be counted as one of the venues in
# a cross-venue median -- that would be a median of a median next to its own
# inputs. tools/emit_latest.py excludes exactly these names.
AGGREGATE_VENUES = frozenset(
    v["name"] for v in VENUES if v.get("parse_fn") is parse_criptoya
)


# ------------------------------------------------------------------ I/O
def get_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_fx(fetch=get_json):
    """Snapshot official USD mids once. -> {ccy: local_per_usd}. Raises on failure."""
    d = fetch(FX_URL)
    rates = d.get("rates") or {}
    if not rates:
        raise ValueError("er-api returned no rates")
    return {k: float(v) for k, v in rates.items()}


# ------------------------------------------------------------- collection
def _base_row(ts, v, name=None):
    return {
        "ts_utc": ts, "venue": name or v["name"], "ccy": v["fiat_ccy"],
        "usdt_bid": None, "usdt_ask": None, "usdt_mid": None,
        "fx_mid_per_usd": None, "basis_bps": None,
        "source": v.get("source") or v["name"].lower(),
        "source_ok": False, "error": "",
    }


def build_rows(ts, venues, fx, fetch=get_json):
    """
    One row per enabled venue. Pure but for `fetch`; injecting `fetch` and `fx`
    is what makes --selftest hermetic. Returns (rows, n_ok).
    n_ok == 0 means total blackout -> the caller exits non-zero.
    """
    rows, n_ok = [], 0
    for v in venues:
        if not v.get("enabled", True):
            continue
        row = _base_row(ts, v)
        payload = None
        try:
            payload = fetch(v["ticker_url"])
            bid, ask, last = v["parse_fn"](payload)
            # Representative price. Order books have tight spreads, so the
            # bid/ask midpoint is the market. CriptoYa aggregates BROKERS whose
            # ask carries ~100 bps of retail markup (spreads of 70-150 bps),
            # so its midpoint is inflated -- mid_rule="bid" takes the clean side.
            # Validated vs our Bitso order book: CriptoYa-MXN median bid matched
            # Bitso mid within a few bps while the midpoint overstated by ~35.
            mid = bid if v.get("mid_rule") == "bid" else mid_of(bid, ask, last)
            fx_mid = fx.get(v["fiat_ccy"])
            if mid is None:
                raise ValueError("no usable venue price")
            if fx_mid is None:
                raise ValueError(f"no FX mid for {v['fiat_ccy']}")
            row.update(
                usdt_bid=bid, usdt_ask=ask, usdt_mid=round(mid, 8),
                fx_mid_per_usd=fx_mid, basis_bps=basis_bps(mid, fx_mid),
                source_ok=True,
            )
            n_ok += 1
        except Exception as e:
            row["error"] = f"{type(e).__name__}:{e}"[:300]
        rows.append(row)

        # An aggregating source can also publish its constituents. One fetch,
        # many rows -- the payload is already in hand, so this costs the venue
        # nothing extra. A break in the expansion must never cost the aggregate
        # row that was just appended, hence the separate try and the payload-is-
        # None guard for the case where the fetch above is what failed.
        expand = v.get("expand_fn")
        if expand and payload is not None:
            try:
                entries = expand(payload)
            except Exception as e:
                row["error"] = (row["error"] or "") + f" expand:{type(e).__name__}"
                entries = []
            for name, e_bid, e_ask, e_last in entries:
                sub = _base_row(ts, v, name=f"CriptoYa:{name}")
                try:
                    e_mid = (e_bid if v.get("mid_rule") == "bid"
                             else mid_of(e_bid, e_ask, e_last))
                    fx_mid = fx.get(v["fiat_ccy"])
                    if e_mid is None:
                        raise ValueError("no usable venue price")
                    if fx_mid is None:
                        raise ValueError(f"no FX mid for {v['fiat_ccy']}")
                    sub.update(
                        usdt_bid=e_bid, usdt_ask=e_ask, usdt_mid=round(e_mid, 8),
                        fx_mid_per_usd=fx_mid, basis_bps=basis_bps(e_mid, fx_mid),
                        source_ok=True,
                    )
                    n_ok += 1
                except Exception as e:
                    sub["error"] = f"{type(e).__name__}:{e}"[:300]
                rows.append(sub)
    return rows, n_ok


def stable_spread_bps(usdt_mid, usdc_mid):
    """How far USDC trades from USDT on the same venue, in bps. None if either
    is missing. Positive = USDC is dearer than USDT in that market."""
    if not usdt_mid or not usdc_mid:
        return None
    return round((usdc_mid / usdt_mid - 1) * 1e4, 2)


def build_stable_rows(ts, venues, usdt_mids, fetch=get_json):
    """One row per venue that quotes BOTH stablecoins against the same currency.

    "Both, in the same hour" is the whole point, so the USDT side is not
    re-fetched: it is the mid this same run already captured for basis.csv,
    passed in. A venue whose USDT pull failed therefore has no USDC row either —
    half a spread is not a spread — and that is recorded, not skipped.

    Venues with no `usdc_url` are absent entirely rather than present with empty
    cells: Bitso has no `usdc_mxn` book at all (the API answers "Unknown
    OrderBook"), and a row of nulls would suggest a market that failed rather
    than one that does not exist.

    Same isolation contract as the wide layer: one venue erroring writes
    source_ok=False and the error string and does not stop the rest.
    """
    rows, n_ok, cache = [], 0, {}

    def fetch_cached(url):
        # Bitkub, Paribu, Pintu and Foxbit publish every pair in one payload, so
        # the USDC url IS the USDT url. One call, two prices.
        if url not in cache:
            cache[url] = fetch(url)
        return cache[url]

    for v in venues:
        if not v.get("enabled", True) or not v.get("usdc_url"):
            continue
        row = {"ts_utc": ts, "venue": v["name"], "ccy": v["fiat_ccy"],
               "usdt_mid": None, "usdc_mid": None, "spread_bps": None,
               "source_ok": False, "error": ""}
        try:
            u_mid = usdt_mids.get(v["name"])
            if u_mid is None:
                raise ValueError("no USDT mid captured this run")
            row["usdt_mid"] = u_mid
            payload = fetch_cached(v["usdc_url"])
            parse = v.get("usdc_parse_fn") or v["parse_fn"]
            bid, ask, last = parse(payload)
            c_mid = bid if v.get("mid_rule") == "bid" else mid_of(bid, ask, last)
            if c_mid is None:
                raise ValueError("no usable USDC price")
            row["usdc_mid"] = round(c_mid, 8)
            row["spread_bps"] = stable_spread_bps(u_mid, c_mid)
            row["source_ok"] = True
            n_ok += 1
        except Exception as e:
            row["error"] = f"{type(e).__name__}:{e}"[:300]
        rows.append(row)
    return rows, n_ok


def append_stable(rows):
    os.makedirs(os.path.dirname(STABLE), exist_ok=True)
    new = not os.path.exists(STABLE)
    with open(STABLE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STABLE_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return STABLE


def print_stable(rows):
    print(f"  USDC vs USDT on the same venue   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 58)
    print(f"  {'VENUE':<20}{'CCY':>5}{'USDT':>12}{'USDC':>12}{'SPREAD':>9}")
    print("  " + "-" * 58)
    for r in rows:
        u = f"{r['usdt_mid']:.5f}" if r["usdt_mid"] is not None else "--"
        c = f"{r['usdc_mid']:.5f}" if r["usdc_mid"] is not None else "--"
        sp = f"{r['spread_bps']:+.1f}bp" if r["spread_bps"] is not None else "--"
        print(f"  {r['venue']:<20}{r['ccy']:>5}{u:>12}{c:>12}{sp:>9}")
    print("  " + "-" * 58)
    for r in [r for r in rows if not r["source_ok"]]:
        print(f"  ! {r['venue']}: {r['error']}")
    bad = sum(1 for r in rows if not r["source_ok"])
    print(f"  {len(rows) - bad}/{len(rows)} venues quote both\n")


def collect(venues=VENUES):
    """One live sample across the registry. Never raises; records failures."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        fx = fetch_fx()
    except Exception as e:
        # Shared dependency down -> every venue will fail cleanly below, which
        # is exactly a total blackout. Record it on every row, don't crash.
        print(f"  [warn] FX snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        fx = {}
    return build_rows(ts, venues, fx)


def run_exit_code(n_ok):
    """Total blackout is the only non-zero exit for the wide layer."""
    return 0 if n_ok > 0 else 1


def utc_hour(now=None):
    """The current UTC hour, truncated -- the idempotency key for a capture."""
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def captured_this_hour(path, ts_field, now=None):
    """True if `path` already holds a row stamped in the current UTC hour.

    The schedule fires at :17 and :47 so that GitHub dropping one fire still
    leaves a capture for the hour. That only buys redundancy if the second fire
    is a no-op when the first landed -- otherwise it buys duplicate rows.

    Rows are append-only and in order, so the last row decides. Deliberately
    duplicated from collector.py rather than shared: the two layers stay
    import-independent, so a break in one cannot take down the other.
    """
    if not os.path.exists(path):
        return False
    last = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            last = row
    if not last or not last.get(ts_field):
        return False
    try:
        ts = dt.datetime.fromisoformat(last[ts_field])
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return utc_hour(ts.astimezone(dt.timezone.utc)) == utc_hour(now)


def append(rows):
    os.makedirs(os.path.dirname(BASIS), exist_ok=True)
    new = not os.path.exists(BASIS)
    with open(BASIS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return BASIS


def print_table(rows):
    print(f"\n  USDT basis vs official USD mid   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 66)
    print(f"  {'VENUE':<20}{'CCY':>5}{'USDT_MID':>12}{'FX_MID':>12}"
          f"{'BASIS':>10}{'OK':>6}")
    print("  " + "-" * 66)
    for r in rows:
        mid = f"{r['usdt_mid']:.5f}" if r["usdt_mid"] is not None else "--"
        fx = f"{r['fx_mid_per_usd']:.5f}" if r["fx_mid_per_usd"] is not None else "--"
        b = f"{r['basis_bps']:+.1f}bp" if r["basis_bps"] is not None else "--"
        ok = "yes" if r["source_ok"] else "NO"
        print(f"  {r['venue']:<20}{r['ccy']:>5}{mid:>12}{fx:>12}{b:>10}{ok:>6}")
    print("  " + "-" * 66)
    bad = [r for r in rows if not r["source_ok"]]
    for r in bad:
        print(f"  ! {r['venue']}: {r['error']}")
    print(f"  {len(rows) - len(bad)}/{len(rows)} venues ok"
          f"{' -- TOTAL BLACKOUT' if len(bad) == len(rows) else ''}\n")


# -------------------------------------------------------------- selftest
# Fixtures are the REAL payload shapes captured live 2026-08-10 (one curl per
# venue). FX values are chosen so the basis assertions are exact.
IR_FIXTURE = {
    "CurrentHighestBidPrice": 1.2805, "CurrentLowestOfferPrice": 1.2815,
    "LastPrice": 1.281, "PrimaryCurrencyCode": "Usdt", "SecondaryCurrencyCode": "Sgd",
}
COINS_FIXTURE = {
    "symbol": "USDTPHP", "bidPrice": "60.58", "bidQty": "255207.28",
    "askPrice": "60.62", "askQty": "360998.21",
}
BTCTURK_FIXTURE = {"data": [{"pair": "USDTTRY", "bid": 47.61, "ask": 47.611,
                             "last": 47.61, "denominatorSymbol": "TRY"}],
                   "success": True, "code": 0}
UPBIT_FIXTURE = [{"market": "KRW-USDT", "trade_price": 1408.0,
                  "opening_price": 1405.0, "timestamp": 1786368748276}]
INDODAX_FIXTURE = {"ticker": {"buy": "17649", "sell": "17650", "last": "17649",
                              "high": "17709", "low": "17600"}}
BITKUB_FIXTURE = {"THB_USDT": {"id": 8, "last": 33.02, "highestBid": 33.02,
                               "lowestAsk": 33.03, "baseVolume": 15532950.29},
                  "THB_USDC": {"id": 9, "last": 33.06, "highestBid": 33.05,
                               "lowestAsk": 33.07, "baseVolume": 210433.11}}
BITSO_FIXTURE = {"success": True, "payload": {"book": "usdt_mxn", "bid": "17.132",
                 "ask": "17.133", "last": "17.132", "high": "17.18"}}
# Captured live from a US GitHub runner 2026-09-02, one call per venue.
BITHUMB_FIXTURE = {"status": "0000", "data": {
    "timestamp": "1788340816643", "payment_currency": "KRW",
    "order_currency": "USDT",
    "bids": [{"price": "1375", "quantity": "1769752.9407"}],
    "asks": [{"price": "1376", "quantity": "785568.5759"}]}}
COINONE_FIXTURE = {"result": "success", "error_code": "0", "tickers": [{
    "quote_currency": "krw", "target_currency": "usdt", "high": "1388.0",
    "low": "1375.0", "first": "1383.0", "last": "1375.0",
    "best_asks": [{"price": "1376.0", "qty": "238491.96539225"}],
    "best_bids": [{"price": "1375.0", "qty": "92249.22447896"}]}]}
PARIBU_FIXTURE = {"USDT_TL": {"chartData": [], "lowestAsk": 48.196,
                              "highestBid": 48.195, "low24hr": 48.182,
                              "high24hr": 48.234, "volume": 6580796.64,
                              "last": 48.195, "percentChange": -0.03},
                  "USDC_TL": {"chartData": [], "lowestAsk": 48.188,
                              "highestBid": 48.179, "volume": 31696.07,
                              "last": 48.179, "percentChange": 0.02}}
# Foxbit ignores ?symbols= and returns every market -- btcbrl really is first.
FOXBIT_FIXTURE = {"data": [
    {"market_symbol": "btcbrl", "last_trade": {"price": "397312.00000000"},
     "best": {"ask": {"price": "397400.00000000"},
              "bid": {"price": "397300.00000000"}}},
    {"market_symbol": "usdtbrl", "last_trade": {"price": "5.16750000"},
     "rolling_24h": {"open": "5.20020000"},
     "best": {"ask": {"price": "5.16750000"}, "bid": {"price": "5.16740000"}}},
    {"market_symbol": "usdcbrl", "last_trade": {"price": "5.17250000"},
     "best": {"ask": {"price": "5.17360000"}, "bid": {"price": "5.17250000"}}}]}
MERCADO_FIXTURE = [{"pair": "USDT-BRL", "high": "5.21820000",
                    "low": "5.14960000", "vol": "1746665.02450000",
                    "last": "5.16930000", "buy": "5.16920000",
                    "sell": "5.16930000", "open": "5.20200000"}]
PINTU_FIXTURE = {"code": "success", "message": "", "payload": [
    {"pair": "cvx/idr", "latestPrice": "42024", "day": "2.21"},
    {"pair": "usdt/idr", "latestPrice": "17734", "day": "0.16"},
    {"pair": "usdc/idr", "latestPrice": "17756", "day": "0.24"}]}

# The USDC side, for venues that publish it on a separate endpoint. Same shapes
# as their USDT payloads -- same parsers, different pair.
IR_USDC_FIXTURE = {"CurrentHighestBidPrice": 1.2812, "CurrentLowestOfferPrice": 1.2822,
                   "LastPrice": 1.2817}
COINS_USDC_FIXTURE = {"symbol": "USDCPHP", "bidPrice": "62.62", "askPrice": "62.63"}
BTCTURK_USDC_FIXTURE = {"data": [{"pair": "USDCTRY", "bid": 48.123, "ask": 48.209,
                                  "last": 48.122}], "success": True}
UPBIT_USDC_FIXTURE = [{"market": "KRW-USDC", "trade_price": 1377.0}]
INDODAX_USDC_FIXTURE = {"ticker": {"buy": "17709", "sell": "17710", "last": "17709"}}
BITHUMB_USDC_FIXTURE = {"status": "0000", "data": {
    "payment_currency": "KRW", "order_currency": "USDC",
    "bids": [{"price": "1375", "quantity": "38817.0528"}],
    "asks": [{"price": "1377", "quantity": "12004.9"}]}}
COINONE_USDC_FIXTURE = {"result": "success", "tickers": [{
    "quote_currency": "krw", "target_currency": "usdc", "last": "1376.0",
    "best_asks": [{"price": "1377.0"}], "best_bids": [{"price": "1375.0"}]}]}
MERCADO_USDC_FIXTURE = [{"pair": "USDC-BRL", "last": "5.17250000",
                         "buy": "5.17250000", "sell": "5.17360000"}]

# CriptoYa general endpoint: many exchanges. Odd counts -> exact medians.
CRIPTOYA_ARS_FIXTURE = {  # median bid 1565, median ask 1585 -> mid 1575
    "belo": {"ask": 1585.0, "bid": 1565.0, "time": 1},
    "buenbit": {"ask": 1580.0, "bid": 1560.0, "time": 1},
    "lemoncash": {"ask": 1620.0, "bid": 1590.0, "time": 1},
}
CRIPTOYA_VES_FIXTURE = {  # median bid 864, median ask 870
    "binancep2p": {"ask": 868.0, "bid": 862.0, "time": 1},
    "eldorado": {"ask": 870.0, "bid": 864.0, "time": 1},
    "syklo": {"ask": 876.0, "bid": 869.0, "time": 1},
}
CRIPTOYA_BRL_FIXTURE = {  # median bid 5.12, median ask 5.15
    "ripio": {"ask": 5.15, "bid": 5.12, "time": 1},
    "foxbit": {"ask": 5.14, "bid": 5.10, "time": 1},
    "mercado": {"ask": 5.33, "bid": 5.13, "time": 1},
}

# One malformed payload per venue: right envelope, no usable price.
MALFORMED = {
    "Bithumb": {"status": "5100", "data": {}},
    "Coinone": {"result": "error", "tickers": []},
    "Paribu": {"BTC_TL": {"last": 1}},          # payload fine, our pair absent
    "Foxbit": {"data": [{"market_symbol": "btcbrl", "best": {}}]},
    "MercadoBitcoin": [],
    "Pintu": {"payload": [{"pair": "btc/idr", "latestPrice": "1"}]},
    "IndependentReserve": {},
    "Coins.ph": {"symbol": "USDTPHP"},
    "CriptoYa": {"buenbit": {"time": 1}},  # exchanges listed, no bid/ask
    "BTCTurk": {"data": [], "success": False},
    "Upbit": [],
    "Indodax": {"ticker": {}},
    "Bitkub": {"THB_USDT": {}},
    "Bitso": {"success": False, "payload": {}},
}

# er-api-style snapshot covering every registered venue's currency. For ARS/VES
# er-api quotes the OFFICIAL rate, so basis is the parallel premium (see #5/#8).
FX_FIXTURE = {"SGD": 1.2796, "PHP": 60.86, "TRY": 47.706, "KRW": 1409.64,
              "IDR": 17862.19, "THB": 33.024, "MXN": 17.141,
              "ARS": 1500.0, "VES": 760.0, "BRL": 5.09}
TS_FIXTURE = "2026-08-10T00:00:00+00:00"

# route a fake fetch by URL substring; override a venue with a payload or an
# Exception instance (raised) to simulate malformed data or an outage. CriptoYa
# keys on the fiat in the path (usdt/ars...) so the three pairs stay distinct.
_ROUTES = {
    # USDC first: these urls also contain the venue's generic key, so a generic
    # match would silently hand back the USDT payload and the spread would read
    # as exactly zero -- a wrong number that looks like a finding.
    "primarycurrencycode=usdc": IR_USDC_FIXTURE, "usdcphp": COINS_USDC_FIXTURE,
    "usdctry": BTCTURK_USDC_FIXTURE, "krw-usdc": UPBIT_USDC_FIXTURE,
    "usdc_idr": INDODAX_USDC_FIXTURE, "usdc_krw": BITHUMB_USDC_FIXTURE,
    "krw/usdc": COINONE_USDC_FIXTURE, "usdc-brl": MERCADO_USDC_FIXTURE,
    "independentreserve": IR_FIXTURE, "coins": COINS_FIXTURE,
    "btcturk": BTCTURK_FIXTURE, "upbit": UPBIT_FIXTURE, "indodax": INDODAX_FIXTURE,
    "bitkub": BITKUB_FIXTURE, "bitso": BITSO_FIXTURE,
    "bithumb": BITHUMB_FIXTURE, "coinone": COINONE_FIXTURE,
    "paribu": PARIBU_FIXTURE, "foxbit": FOXBIT_FIXTURE,
    "mercadobitcoin": MERCADO_FIXTURE, "pintu": PINTU_FIXTURE,
    "usdt/ars": CRIPTOYA_ARS_FIXTURE, "usdt/ves": CRIPTOYA_VES_FIXTURE,
    "usdt/brl": CRIPTOYA_BRL_FIXTURE,
}


def _make_fetch(overrides=None):
    overrides = overrides or {}

    def fetch(url):
        u = url.lower()
        for key, payload in _ROUTES.items():
            if key in u:
                val = overrides.get(key, payload)
                if isinstance(val, Exception):
                    raise val
                return val
        raise KeyError(url)
    return fetch


def selftest():
    # 1. every parser extracts (bid, ask, last) from its real payload shape
    assert parse_independent_reserve(IR_FIXTURE) == (1.2805, 1.2815, 1.281)
    assert parse_coins_pro(COINS_FIXTURE) == (60.58, 60.62, None)
    assert parse_btcturk(BTCTURK_FIXTURE) == (47.61, 47.611, 47.61)
    assert parse_upbit(UPBIT_FIXTURE) == (None, None, 1408.0)      # KRW quote = last
    assert parse_indodax(INDODAX_FIXTURE) == (17649.0, 17650.0, 17649.0)
    assert parse_bitkub(BITKUB_FIXTURE) == (33.02, 33.03, 33.02)
    assert parse_bitso(BITSO_FIXTURE) == (17.132, 17.133, 17.132)
    # CriptoYa: median bid/ask across the listed exchanges
    assert parse_criptoya(CRIPTOYA_ARS_FIXTURE) == (1565.0, 1585.0, None)
    # 2026-09-02 venues
    assert parse_bithumb(BITHUMB_FIXTURE) == (1375.0, 1376.0, None)
    assert parse_coinone(COINONE_FIXTURE) == (1375.0, 1376.0, 1375.0)
    assert parse_paribu(PARIBU_FIXTURE) == (48.195, 48.196, 48.195)
    # Foxbit: the right market is picked out of a list that starts with btcbrl
    assert parse_foxbit(FOXBIT_FIXTURE) == (5.1674, 5.1675, 5.1675)
    assert parse_mercadobitcoin(MERCADO_FIXTURE) == (5.1692, 5.1693, 5.1693)
    # Pintu publishes no book: last only, and the right pair out of the list
    assert parse_pintu(PINTU_FIXTURE) == (None, None, 17734.0)
    print("  [ok] all 14 parsers extract quotes from real payload shapes "
          "(CriptoYa = median across exchanges)")

    # 2. every parser degrades a malformed payload to all-None, never raises
    _parsers = {
        "IndependentReserve": parse_independent_reserve, "Coins.ph": parse_coins_pro,
        "BTCTurk": parse_btcturk, "Upbit": parse_upbit, "Indodax": parse_indodax,
        "Bitkub": parse_bitkub, "Bitso": parse_bitso, "CriptoYa": parse_criptoya,
        "Bithumb": parse_bithumb, "Coinone": parse_coinone, "Paribu": parse_paribu,
        "Foxbit": parse_foxbit, "MercadoBitcoin": parse_mercadobitcoin,
        "Pintu": parse_pintu,
    }
    for name, pf in _parsers.items():
        assert pf(MALFORMED[name]) == (None, None, None), (name, pf(MALFORMED[name]))
    assert parse_criptoya([]) == (None, None, None)  # non-dict envelope
    print("  [ok] all 14 parsers turn a malformed payload into (None, None, None)")

    # 2b. the expander drops P2P books and survives a malformed payload
    ves = expand_criptoya(CRIPTOYA_VES_FIXTURE)
    assert [n for n, *_ in ves] == ["eldorado", "syklo"], ves  # binancep2p dropped
    assert ves[0] == ("eldorado", 864.0, 870.0, None), ves[0]
    assert expand_criptoya({}) == [] and expand_criptoya([]) == []
    assert expand_criptoya({"buenbit": {"time": 1}}) == []     # listed, no prices
    print("  [ok] expander: one entry per exchange, P2P dropped, malformed -> []")

    # 3. basis math, both signs; mid fallback ladder
    assert abs(basis_bps(1.2810, 1.2796) - 10.94) < 0.1     # SG: barely rich
    assert abs(basis_bps(60.60, 60.86) - (-42.72)) < 0.1    # PH: USDT trades cheap
    assert basis_bps(None, 1.0) is None and basis_bps(1.0, None) is None
    assert mid_of(1.0, 2.0, 9.0) == 1.5 and mid_of(None, None, 9.0) == 9.0
    assert mid_of(None, 2.0, None) == 2.0 and mid_of(None, None, None) is None
    print("  [ok] basis sign +rich/-cheap, None-safe; mid falls back to last/side")

    # 4. FX snapshot must carry every registered venue's currency
    ccys = {v["fiat_ccy"] for v in VENUES}
    assert ccys <= set(FX_FIXTURE), ccys - set(FX_FIXTURE)
    assert len(VENUES) == 16, len(VENUES)
    assert {"TRY", "KRW", "IDR", "THB", "MXN"} <= ccys, "the 5 new currencies"
    assert {"ARS", "VES", "BRL"} <= ccys, "the CriptoYa currencies"
    print(f"  [ok] FX snapshot covers all {len(ccys)} venue currencies "
          f"({', '.join(sorted(ccys))})")

    # 5. full happy path: 16 registered venues + 5 CriptoYa expansion rows
    #    (ARS lists 3 exchanges, VES lists 3 of which one is P2P), all source_ok
    rows, n_ok = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=_make_fetch())
    assert len(rows) == 21 and n_ok == 21, (len(rows), n_ok)
    by = {r["venue"]: r for r in rows}
    assert abs(by["IndependentReserve"]["basis_bps"] - 10.94) < 0.2
    assert abs(by["Bitso"]["basis_bps"] - (-4.96)) < 0.2          # MXN near zero
    # inversion guard: a flipped TRY parse would read +thousands; real is ~-20.
    assert -200 < by["BTCTurk"]["basis_bps"] < 50, by["BTCTurk"]["basis_bps"]
    # CriptoYa uses mid_rule="bid": representative price = median bid (1565),
    # NOT the inflated bid/ask midpoint (1575). basis = 1565/1500-1 = +433 bps.
    ars = by["CriptoYa (ARS)"]
    assert ars["usdt_mid"] == ars["usdt_bid"] == 1565.0, ars   # bid rule applied
    assert ars["usdt_ask"] == 1585.0                           # ask still shown
    assert abs(ars["basis_bps"] - 433.33) < 1.0, ars           # bid, not midpoint
    assert by["CriptoYa (VES)"]["basis_bps"] > 1000, by["CriptoYa (VES)"]  # strong
    assert ars["source"] == "criptoya"                         # snapshot-only tag
    print("  [ok] 21/21 rows price; CriptoYa on bid rule (ARS +433, not +500 midpoint)")

    # 5b. the point of the whole change: how many venues answer per currency.
    #     KRW/BRL gain real venues; ARS gains them through the expansion; and
    #     SGD/PHP/THB/MXN honestly still have one, which the site must say.
    per_ccy = collections.Counter(
        r["ccy"] for r in rows
        if r["source_ok"] and r["venue"] not in AGGREGATE_VENUES)
    assert per_ccy["KRW"] == 3, per_ccy          # Upbit, Bithumb, Coinone
    assert per_ccy["BRL"] == 2, per_ccy          # Foxbit, MercadoBitcoin
    assert per_ccy["TRY"] == 2 and per_ccy["IDR"] == 2, per_ccy
    assert per_ccy["ARS"] == 3, per_ccy          # expansion rows only
    assert per_ccy["VES"] == 2, per_ccy          # expansion, P2P dropped
    for single in ("SGD", "PHP", "THB", "MXN"):
        assert per_ccy[single] == 1, (single, per_ccy)
    # the aggregate row is still written, and still excluded from that count
    assert any(r["venue"] == "CriptoYa (ARS)" and r["source_ok"] for r in rows)
    assert "CriptoYa (ARS)" in AGGREGATE_VENUES
    # expansion rows are named for their exchange and carry the criptoya source
    belo = next(r for r in rows if r["venue"] == "CriptoYa:belo")
    assert belo["ccy"] == "ARS" and belo["source"] == "criptoya"
    assert belo["usdt_mid"] == belo["usdt_bid"] == 1565.0, belo   # bid rule
    assert not any(r["venue"].endswith("p2p") for r in rows), "P2P leaked in"
    print(f"  [ok] venues per currency: "
          f"{', '.join(f'{c}={n}' for c, n in sorted(per_ccy.items()))}")

    # 6. per-venue isolation: one outage + one malformed payload, run continues
    fetch = _make_fetch({"coins": RuntimeError("simulated 503 from Coins.ph"),
                         "bitkub": MALFORMED["Bitkub"]})
    rows_m, n_ok_m = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=fetch)
    co = next(r for r in rows_m if r["venue"] == "Coins.ph")
    bk = next(r for r in rows_m if r["venue"] == "Bitkub")
    assert n_ok_m == 19, n_ok_m  # 21 - coins(outage) - bitkub(malformed)
    assert co["source_ok"] is False and "simulated 503" in co["error"]
    assert bk["source_ok"] is False and bk["basis_bps"] is None
    assert run_exit_code(n_ok_m) == 0  # 5 good venues -> the run SUCCEEDS
    print("  [ok] outage + malformed venue -> source_ok=False rows, run exits 0")

    # 7. missing FX for one ccy degrades only that venue
    fx_no_thb = {k: v for k, v in FX_FIXTURE.items() if k != "THB"}
    rows_f, _ = build_rows(TS_FIXTURE, VENUES, fx_no_thb, fetch=_make_fetch())
    bk_f = next(r for r in rows_f if r["venue"] == "Bitkub")
    assert bk_f["source_ok"] is False and "no FX mid for THB" in bk_f["error"]
    print("  [ok] missing FX mid degrades only its venue")

    # 8. total blackout is the only non-zero exit
    fetch_dead = _make_fetch({k: RuntimeError("down") for k in _ROUTES})
    rows_b, n_ok_b = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=fetch_dead)
    assert n_ok_b == 0 and all(not r["source_ok"] for r in rows_b)
    assert run_exit_code(n_ok_b) == 1
    print("  [ok] total blackout (all venues fail) -> run exits non-zero")

    assert set(FIELDS) >= set(_base_row(TS_FIXTURE, VENUES[0]))
    print("  [ok] schema covers every row field")

    # 9. USDT vs USDC on the same venue, same hour
    assert stable_spread_bps(33.02, 33.06) == 12.11, stable_spread_bps(33.02, 33.06)
    assert stable_spread_bps(None, 1.0) is None and stable_spread_bps(1.0, 0) is None
    usdt_mids = {r["venue"]: r["usdt_mid"] for r in rows if r["source_ok"]}
    srows, sok = build_stable_rows(TS_FIXTURE, VENUES, usdt_mids, fetch=_make_fetch())
    assert len(srows) == 12 and sok == 12, (len(srows), sok)
    sby = {r["venue"]: r for r in srows}
    # Bitso has no usdc_mxn book at all -- absent, not a row of nulls
    assert "Bitso" not in sby and not any(r["ccy"] == "MXN" for r in srows)
    # the four combined payloads must read the USDC pair, not hand back USDT
    for name in ("Bitkub", "Paribu", "Pintu", "Foxbit"):
        assert sby[name]["usdc_mid"] != sby[name]["usdt_mid"], name
        assert sby[name]["spread_bps"] not in (None, 0.0), (name, sby[name])
    # Bitkub: USDT mid 33.025, USDC mid 33.06 -> USDC dearer by 10.6 bps.
    # Both are MIDS, not last prices -- the fixture's last prices would give
    # 12.11, and reading the wrong field is exactly the mistake to catch here.
    assert abs(sby["Bitkub"]["spread_bps"] - 10.6) < 0.1, sby["Bitkub"]
    # the USDT side is the mid this run already captured, never re-fetched
    assert sby["Bitkub"]["usdt_mid"] == by["Bitkub"]["usdt_mid"]
    assert set(STABLE_FIELDS) >= set(srows[0])
    print(f"  [ok] USDT/USDC: {sok}/{len(srows)} venues quote both; "
          f"Bitso absent (no usdc_mxn book)")

    # 10. half a spread is not a spread: a venue whose USDT pull failed gets a
    #     row saying so rather than a USDC price with nothing to compare it to
    srows_h, sok_h = build_stable_rows(
        TS_FIXTURE, VENUES, {k: v for k, v in usdt_mids.items() if k != "Upbit"},
        fetch=_make_fetch())
    up = next(r for r in srows_h if r["venue"] == "Upbit")
    assert up["source_ok"] is False and "no USDT mid" in up["error"], up
    assert up["usdc_mid"] is None and up["spread_bps"] is None, up
    assert sok_h == 11, sok_h
    # and one venue's USDC endpoint dying does not touch the others
    srows_o, sok_o = build_stable_rows(
        TS_FIXTURE, VENUES, usdt_mids,
        fetch=_make_fetch({"usdc_krw": RuntimeError("simulated 503")}))
    bh = next(r for r in srows_o if r["venue"] == "Bithumb")
    assert bh["source_ok"] is False and "simulated 503" in bh["error"]
    assert sok_o == 11, sok_o
    print("  [ok] USDT/USDC: missing USDT mid and a dead endpoint isolate to "
          "their own row\n")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "basis.csv")
        assert captured_this_hour(p, "ts_utc") is False, "missing file -> not captured"
        now = dt.datetime(2026, 8, 18, 14, 5, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts_utc", "venue"]).writeheader()
        assert captured_this_hour(p, "ts_utc", now) is False, "header only"
        # the wide layer writes one row PER VENUE per run; the last one decides
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "venue"])
            for v in ("Upbit", "Bitso", "CriptoYa (BRL)"):
                w.writerow({"ts_utc": "2026-08-18T13:47:33.670000+00:00", "venue": v})
        assert captured_this_hour(p, "ts_utc", now) is False, "prior hour"
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "venue"])
            for v in ("Upbit", "Bitso", "CriptoYa (BRL)"):
                w.writerow({"ts_utc": "2026-08-18T14:17:33.670000+00:00", "venue": v})
        assert captured_this_hour(p, "ts_utc", now) is True, "same hour -> captured"
        assert captured_this_hour(
            p, "ts_utc", now.replace(minute=47)) is True, ":47 sees :17's rows"
        assert captured_this_hour(
            p, "ts_utc", now.replace(hour=15)) is False, "new hour reopens"
    print("  [ok] idempotency gate: one capture per UTC hour, reopens on the next\n")

    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki basis collector (wide layer)")
    ap.add_argument("--verify", action="store_true",
                    help="one live pull, print, write nothing (RUN THIS FIRST)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    # Idempotency gate, BEFORE the network: the schedule fires twice an hour so
    # a dropped fire has a partner, not so we capture twice. Gating here also
    # spares the venues a redundant pull on the second fire.
    if not a.verify and captured_this_hour(BASIS, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {BASIS}, nothing to do")
        return

    rows, n_ok = collect()

    # PERSIST FIRST, DISPLAY SECOND -- a formatting bug in print_table() must
    # never be able to cost a captured row. See collector.py for the incident.
    if not a.verify:
        append(rows)

    # USDT vs USDC on the same venue, in the same hour, off the mids just
    # captured. Gated on ITS OWN file: the layer is newer than basis.csv, so an
    # hour where basis already landed can still be the first hour this file has.
    # Failing here must never cost the basis rows, which are already on disk.
    stable_rows, stable_ok = [], 0
    if a.verify or not captured_this_hour(STABLE, "ts_utc"):
        usdt_mids = {r["venue"]: r["usdt_mid"] for r in rows if r["source_ok"]}
        ts = rows[0]["ts_utc"] if rows else dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            stable_rows, stable_ok = build_stable_rows(ts, VENUES, usdt_mids)
        except Exception as e:
            print(f"  [warn] stable layer failed entirely: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
        if stable_rows and not a.verify:
            append_stable(stable_rows)

    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)
        if stable_rows:
            print_stable(stable_rows)

    if a.verify:
        return

    print(f"  appended -> {BASIS}")
    if stable_rows:
        print(f"  appended -> {STABLE}")
    print()
    # loud failure: only a total blackout goes red, per the wide-layer contract
    if run_exit_code(n_ok) != 0:
        print("  [error] TOTAL BLACKOUT -- every venue failed this run", file=sys.stderr)
        sys.exit(1)
    # Same contract for the stable layer, and only when it actually ran: every
    # venue that quotes both stablecoins failing at once is an outage, not a
    # market. A hour it skipped (already captured) is silent, as it should be.
    if stable_rows and stable_ok == 0:
        print("  [error] every venue failed the USDT/USDC pull this run",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
