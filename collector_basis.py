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
UA = {"User-Agent": "margin.wiki basis-collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
BASIS = os.path.join(HERE, "data", "basis.csv")
FX_URL = "https://open.er-api.com/v6/latest/USD"

FIELDS = [
    "ts_utc", "venue", "ccy",
    "usdt_bid", "usdt_ask", "usdt_mid",
    "fx_mid_per_usd", "basis_bps",
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


def parse_bitkub(d):
    # market/ticker: all pairs keyed by "THB_USDT" -> {"highestBid","lowestAsk","last"}.
    t = d.get("THB_USDT") or {}
    return (_f(t.get("highestBid")), _f(t.get("lowestAsk")), _f(t.get("last")))


def parse_bitso(d):
    # v3/ticker: {"success":bool,"payload":{"bid","ask","last",...}}. String-priced.
    p = d.get("payload") or {}
    return (_f(p.get("bid")), _f(p.get("ask")), _f(p.get("last")))


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
        "enabled": True,
    },
    {
        "name": "Upbit",
        "fiat_ccy": "KRW",
        "ticker_url": "https://api.upbit.com/v1/ticker?markets=KRW-USDT",
        "parse_fn": parse_upbit,
        "candles_fn": None,
        "enabled": True,
    },
    {
        "name": "Indodax",
        "fiat_ccy": "IDR",
        "ticker_url": "https://indodax.com/api/usdt_idr/ticker",
        "parse_fn": parse_indodax,
        "candles_fn": None,
        "enabled": True,
    },
    {
        "name": "Bitkub",
        "fiat_ccy": "THB",
        "ticker_url": "https://api.bitkub.com/api/market/ticker",
        "parse_fn": parse_bitkub,
        "candles_fn": None,
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
]


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
def _base_row(ts, v):
    return {
        "ts_utc": ts, "venue": v["name"], "ccy": v["fiat_ccy"],
        "usdt_bid": None, "usdt_ask": None, "usdt_mid": None,
        "fx_mid_per_usd": None, "basis_bps": None,
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
        try:
            payload = fetch(v["ticker_url"])
            bid, ask, last = v["parse_fn"](payload)
            mid = mid_of(bid, ask, last)
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
    return rows, n_ok


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
                               "lowestAsk": 33.03, "baseVolume": 15532950.29}}
BITSO_FIXTURE = {"success": True, "payload": {"book": "usdt_mxn", "bid": "17.132",
                 "ask": "17.133", "last": "17.132", "high": "17.18"}}

# One malformed payload per venue: right envelope, no usable price.
MALFORMED = {
    "IndependentReserve": {},
    "Coins.ph": {"symbol": "USDTPHP"},
    "BTCTurk": {"data": [], "success": False},
    "Upbit": [],
    "Indodax": {"ticker": {}},
    "Bitkub": {"THB_USDT": {}},
    "Bitso": {"success": False, "payload": {}},
}

# er-api-style snapshot covering every registered venue's currency.
FX_FIXTURE = {"SGD": 1.2796, "PHP": 60.86, "TRY": 47.706, "KRW": 1409.64,
              "IDR": 17862.19, "THB": 33.024, "MXN": 17.141}
TS_FIXTURE = "2026-08-10T00:00:00+00:00"

# route a fake fetch by URL substring; override a venue with a payload or an
# Exception instance (raised) to simulate malformed data or an outage.
_ROUTES = {
    "independentreserve": IR_FIXTURE, "coins": COINS_FIXTURE,
    "btcturk": BTCTURK_FIXTURE, "upbit": UPBIT_FIXTURE, "indodax": INDODAX_FIXTURE,
    "bitkub": BITKUB_FIXTURE, "bitso": BITSO_FIXTURE,
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
    print("  [ok] all 7 parsers extract (bid, ask, last) from real payload shapes")

    # 2. every parser degrades a malformed payload to all-None, never raises
    _parsers = {
        "IndependentReserve": parse_independent_reserve, "Coins.ph": parse_coins_pro,
        "BTCTurk": parse_btcturk, "Upbit": parse_upbit, "Indodax": parse_indodax,
        "Bitkub": parse_bitkub, "Bitso": parse_bitso,
    }
    for name, pf in _parsers.items():
        assert pf(MALFORMED[name]) == (None, None, None), (name, pf(MALFORMED[name]))
    print("  [ok] all 7 parsers turn a malformed payload into (None, None, None)")

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
    assert {"TRY", "KRW", "IDR", "THB", "MXN"} <= ccys, "the 5 new currencies"
    print(f"  [ok] FX snapshot covers all {len(ccys)} venue currencies "
          f"({', '.join(sorted(ccys))})")

    # 5. full happy path: all 7 venues price, all source_ok
    rows, n_ok = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=_make_fetch())
    assert len(rows) == 7 and n_ok == 7, (len(rows), n_ok)
    by = {r["venue"]: r for r in rows}
    assert abs(by["IndependentReserve"]["basis_bps"] - 10.94) < 0.2
    assert abs(by["Bitso"]["basis_bps"] - (-4.96)) < 0.2          # MXN near zero
    # inversion guard: a flipped TRY parse would read +thousands; real is ~-20.
    assert -200 < by["BTCTurk"]["basis_bps"] < 50, by["BTCTurk"]["basis_bps"]
    print("  [ok] 7/7 venues price; MXN~0, TRY in-band (parse not inverted)")

    # 6. per-venue isolation: one outage + one malformed payload, run continues
    fetch = _make_fetch({"coins": RuntimeError("simulated 503 from Coins.ph"),
                         "bitkub": MALFORMED["Bitkub"]})
    rows_m, n_ok_m = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=fetch)
    co = next(r for r in rows_m if r["venue"] == "Coins.ph")
    bk = next(r for r in rows_m if r["venue"] == "Bitkub")
    assert n_ok_m == 5, n_ok_m
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
    print("  [ok] schema covers every row field\n")
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

    rows, n_ok = collect()

    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)

    if a.verify:
        return

    append(rows)
    print(f"  appended -> {BASIS}\n")
    # loud failure: only a total blackout goes red, per the wide-layer contract
    if run_exit_code(n_ok) != 0:
        print("  [error] TOTAL BLACKOUT -- every venue failed this run", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
