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
# Fixtures are the REAL payload shapes captured 2026-08-10 (see the curl in the
# commit). FX values are chosen to make the basis assertions exact.
IR_FIXTURE = {
    "CurrentHighestBidPrice": 1.2805, "CurrentLowestOfferPrice": 1.2815,
    "LastPrice": 1.281, "PrimaryCurrencyCode": "Usdt", "SecondaryCurrencyCode": "Sgd",
}
COINS_FIXTURE = {
    "symbol": "USDTPHP", "bidPrice": "60.58", "bidQty": "255207.28",
    "askPrice": "60.62", "askQty": "360998.21",
}
FX_FIXTURE = {"SGD": 1.2796, "PHP": 60.86}
TS_FIXTURE = "2026-08-10T00:00:00+00:00"


def selftest():
    # 1. parsers handle the real shapes (dict, string-priced)
    assert parse_independent_reserve(IR_FIXTURE) == (1.2805, 1.2815, 1.281)
    assert parse_coins_pro(COINS_FIXTURE) == (60.58, 60.62, None)
    print("  [ok] parsers extract (bid, ask, last) from both real payload shapes")

    # 2. basis math, both signs
    assert abs(basis_bps(1.2810, 1.2796) - 10.94) < 0.1     # SG: barely rich
    assert abs(basis_bps(60.60, 60.86) - (-42.72)) < 0.1    # PH: USDT trades cheap
    assert basis_bps(None, 1.0) is None and basis_bps(1.0, None) is None
    print("  [ok] basis: +10.9 bps (SGD anchor) / -42.7 bps (PHP); None-safe")

    # 3. mid fallback ladder
    assert mid_of(1.0, 2.0, 9.0) == 1.5     # prefer bid/ask midpoint
    assert mid_of(None, None, 9.0) == 9.0   # fall back to last
    assert mid_of(None, 2.0, None) == 2.0   # then a single side
    assert mid_of(None, None, None) is None
    print("  [ok] mid falls back bid/ask -> last -> one side -> None")

    # 4. per-venue failure isolation: one venue 503s, the run continues
    def fetch_one_down(url):
        if "independentreserve" in url:
            return IR_FIXTURE
        if "coins" in url:
            raise RuntimeError("simulated 503 from Coins.ph")
        raise KeyError(url)

    rows, n_ok = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=fetch_one_down)
    assert len(rows) == 2, rows
    assert n_ok == 1, n_ok
    ir = next(r for r in rows if r["venue"] == "IndependentReserve")
    co = next(r for r in rows if r["venue"] == "Coins.ph")
    assert ir["source_ok"] is True and abs(ir["basis_bps"] - 10.94) < 0.2, ir
    assert co["source_ok"] is False and co["basis_bps"] is None, co
    assert "simulated 503" in co["error"], co["error"]
    assert run_exit_code(n_ok) == 0  # one good venue -> the run SUCCEEDS
    print("  [ok] one venue down -> its row is source_ok=False, run still exits 0")

    # 5. total blackout is the only non-zero exit
    def fetch_all_down(url):
        raise RuntimeError("everything is on fire")

    rows_b, n_ok_b = build_rows(TS_FIXTURE, VENUES, FX_FIXTURE, fetch=fetch_all_down)
    assert n_ok_b == 0 and all(not r["source_ok"] for r in rows_b)
    assert run_exit_code(n_ok_b) == 1  # every venue failed -> exit non-zero
    print("  [ok] total blackout (all venues fail) -> run exits non-zero")

    # 6. missing FX for a ccy fails only that venue, cleanly
    rows_f, n_ok_f = build_rows(TS_FIXTURE, VENUES, {"SGD": 1.2796},
                                fetch=fetch_one_down)
    co_f = next(r for r in rows_f if r["venue"] == "Coins.ph")
    assert "no FX mid for PHP" in co_f["error"] or "simulated" in co_f["error"]
    print("  [ok] missing FX mid degrades one venue, not the run")

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
