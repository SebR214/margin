#!/usr/bin/env python3
"""
margin.wiki P2P collector -- the CAPITAL-CONTROLLED layer.

Ten currencies with no licensed spot USDT book to read: NGN, EGP, PKR, BDT,
VND, KES, GHS, BOB, LBP, ETB. Where `collector_basis.py` reads an order book,
this reads an advertisement board, and the difference matters enough that it
gets its own file rather than a source column in basis.csv.

A P2P ad is NOT an order-book quote. It is a price someone is asking, with
counterparty risk, a payment-method requirement and a settlement window; it is
not a fill and nothing guarantees one exists at that price. It is still the
only price these markets have, which is exactly why it is collected and exactly
why it is kept apart.

    basis_bps = (mid / fx_mid_local_per_usd - 1) * 10_000

Method, per currency, per hour:
  - top 10 BUY-side ads and top 10 SELL-side ads for USDT, filtered to an
    amount worth about USD 500, so the number is a price a normal person could
    actually transact at rather than the thin best ad on the board.
  - the MEDIAN of each side, stored separately, and their midpoint.

Same contract as the wide layer:
  - Per-currency failure isolation. One currency erroring, or simply having no
    ads, writes source_ok=False with the reason; it does not kill the run.
  - The run exits non-zero ONLY on a total blackout (no currency priced).
  - FX mid is snapshotted ONCE per run and shared.
  - One capture per UTC hour, gated on this file's own newest row.

Source: Binance P2P's public search endpoint. Bybit's P2P endpoint is
geo-blocked from GitHub's US runners (CloudFront 403, "configured to block
access from your country", verified 2026-09-02), so it is not used and not
faked. See ROADMAP, "P2P layer".

Usage:
  python3 collector_p2p.py --verify     # one live pull, print, write nothing
  python3 collector_p2p.py              # one pull, append data/p2p_basis.csv
  python3 collector_p2p.py --selftest   # offline, mocked board + failures
"""

import argparse
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

HTTP_TIMEOUT = 25
UA = {"User-Agent": "margin.wiki p2p-collector/1.0 (+https://margin.wiki)",
      "content-type": "application/json"}
HERE = os.path.dirname(os.path.abspath(__file__))
P2P = os.path.join(HERE, "data", "p2p_basis.csv")
FX_URL = "https://open.er-api.com/v6/latest/USD"

SEARCH_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
SOURCE = "binance_p2p"

# The amount the price has to be good for. The best ad on a P2P board is often
# for a trivial size; filtering to a realistic ticket is what makes the median
# mean something. USD, converted per currency from the same FX snapshot.
FILTER_USD = 500
ROWS = 10

# Every currency asked for, including the three that currently return no ads.
# They stay in the list on purpose: an empty board is a finding about the market
# and is recorded as a row, not omitted as if it had never been asked.
CURRENCIES = ["NGN", "EGP", "PKR", "BDT", "VND", "KES", "GHS", "BOB", "LBP", "ETB"]

FIELDS = [
    "ts_utc", "source", "ccy",
    "buy_median", "sell_median", "mid",
    "fx_mid_per_usd", "basis_bps", "n_ads",
    "source_ok", "error",
]


# ------------------------------------------------------------- pure core
def _f(x):
    """Coerce to a positive float, or None. Prices come back as strings."""
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def prices_from(payload):
    """Ad-board payload -> list of prices, local per USDT, in board order.

    Anything without a usable price is dropped rather than guessed at. A
    payload that is the right shape and simply empty yields [], which is a real
    answer about that market and is treated as one by the caller.
    """
    if not isinstance(payload, dict):
        return []
    out = []
    for row in (payload.get("data") or []):
        if not isinstance(row, dict):
            continue
        p = _f((row.get("adv") or {}).get("price"))
        if p is not None:
            out.append(p)
    return out


def basis_bps(mid, fx_mid):
    """P2P mid against the official USD mid, in bps. None if either is missing."""
    if not mid or not fx_mid:
        return None
    return round((mid / fx_mid - 1) * 1e4, 2)


def summarise(buys, sells):
    """(buy_median, sell_median, mid, n_ads) from the two sides of the board.

    Both sides are stored because on a P2P board the spread between them is not
    a rounding detail -- it is the cost of the market, and in a currency under
    capital controls it can be several percent. The mid is their midpoint, and
    it needs BOTH sides: one side alone is an asking price, not a market.
    """
    b = statistics.median(buys) if buys else None
    s = statistics.median(sells) if sells else None
    mid = (b + s) / 2 if (b is not None and s is not None) else None
    return b, s, mid, len(buys) + len(sells)


# ------------------------------------------------------------------ I/O
def post_json(url, body):
    r = requests.post(url, json=body, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


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


def search_body(ccy, trade_type, trans_amount):
    return {
        "page": 1, "rows": ROWS, "asset": "USDT", "fiat": ccy,
        "tradeType": trade_type, "payTypes": [], "publisherType": None,
        "transAmount": str(trans_amount),
    }


# ------------------------------------------------------------- collection
def _base_row(ts, ccy):
    return {
        "ts_utc": ts, "source": SOURCE, "ccy": ccy,
        "buy_median": None, "sell_median": None, "mid": None,
        "fx_mid_per_usd": None, "basis_bps": None, "n_ads": 0,
        "source_ok": False, "error": "",
    }


def build_rows(ts, currencies, fx, post=post_json):
    """One row per currency. Pure but for `post`. Returns (rows, n_ok)."""
    rows, n_ok = [], 0
    for ccy in currencies:
        row = _base_row(ts, ccy)
        try:
            fx_mid = fx.get(ccy)
            if fx_mid is None:
                raise ValueError(f"no FX mid for {ccy}")
            row["fx_mid_per_usd"] = fx_mid
            # The amount filter is in local currency, so it depends on the FX
            # snapshot -- which is why it is computed here and not a constant.
            amount = int(round(FILTER_USD * fx_mid))
            buys = prices_from(post(SEARCH_URL, search_body(ccy, "BUY", amount)))
            sells = prices_from(post(SEARCH_URL, search_body(ccy, "SELL", amount)))
            b, s, mid, n = summarise(buys, sells)
            row["n_ads"] = n
            if mid is None:
                # No board, or only one side of one. Both are real facts about
                # the market and neither is a half-price worth publishing.
                raise ValueError(
                    "no ads at ~USD %d (%d buy, %d sell)" % (FILTER_USD, len(buys), len(sells)))
            row.update(buy_median=round(b, 8), sell_median=round(s, 8),
                       mid=round(mid, 8), basis_bps=basis_bps(mid, fx_mid),
                       source_ok=True)
            n_ok += 1
        except Exception as e:
            row["error"] = f"{type(e).__name__}:{e}"[:300]
        rows.append(row)
    return rows, n_ok


def collect(currencies=CURRENCIES):
    """One live sample across the currency list. Never raises; records failures."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        fx = fetch_fx()
    except Exception as e:
        print(f"  [warn] FX snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        fx = {}
    return build_rows(ts, currencies, fx)


def run_exit_code(n_ok):
    """Total blackout is the only non-zero exit, as in the wide layer."""
    return 0 if n_ok > 0 else 1


def utc_hour(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def captured_this_hour(path, ts_field, now=None):
    """True if `path` already holds a row stamped in the current UTC hour.

    Deliberately duplicated from the other collectors rather than shared: the
    layers stay import-independent, so a break in one cannot take down another.
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
        t = dt.datetime.fromisoformat(last[ts_field])
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return utc_hour(t.astimezone(dt.timezone.utc)) == utc_hour(now)


def append(rows):
    os.makedirs(os.path.dirname(P2P), exist_ok=True)
    new = not os.path.exists(P2P)
    with open(P2P, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return P2P


def print_table(rows):
    print(f"\n  USDT on P2P boards vs official USD mid   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 72)
    print(f"  {'CCY':<5}{'BUY':>14}{'SELL':>14}{'MID':>14}{'FX':>12}{'BASIS':>10}{'ADS':>5}")
    print("  " + "-" * 72)
    for r in rows:
        g = lambda k, d=5: f"{r[k]:,.{d}f}" if r[k] is not None else "--"
        b = f"{r['basis_bps']:+.1f}" if r["basis_bps"] is not None else "--"
        print(f"  {r['ccy']:<5}{g('buy_median',2):>14}{g('sell_median',2):>14}"
              f"{g('mid',2):>14}{g('fx_mid_per_usd',2):>12}{b:>10}{r['n_ads']:>5}")
    print("  " + "-" * 72)
    bad = [r for r in rows if not r["source_ok"]]
    for r in bad:
        print(f"  ! {r['ccy']}: {r['error']}")
    print(f"  {len(rows) - len(bad)}/{len(rows)} currencies priced"
          f"{' -- TOTAL BLACKOUT' if len(bad) == len(rows) else ''}\n")


# -------------------------------------------------------------- selftest
def _board(prices):
    """A payload in the real shape, from the live response captured 2026-09-02."""
    return {"code": "000000", "success": True,
            "data": [{"adv": {"advNo": str(i), "asset": "USDT", "price": str(p),
                              "tradeType": "SELL", "fiatUnit": "VND"},
                      "advertiser": {"nickName": "n%d" % i}}
                     for i, p in enumerate(prices)]}


EMPTY_BOARD = {"code": "000000", "success": True, "data": [], "total": 0}
FX_FIXTURE = {"NGN": 1332.607355, "EGP": 50.924246, "PKR": 277.866264,
              "BDT": 122.692712, "VND": 26007.437228, "KES": 129.481429,
              "GHS": 11.266187, "BOB": 11.879488, "LBP": 89500.0,
              "ETB": 161.438389}
TS_FIXTURE = "2026-09-02T00:00:00+00:00"


def _make_post(overrides=None, empty=()):
    """Fake board: BUY 1% over the official rate, SELL 1% under, per currency."""
    overrides = overrides or {}

    def post(url, body):
        ccy = body["fiat"]
        if ccy in overrides:
            val = overrides[ccy]
            if isinstance(val, Exception):
                raise val
            return val
        if ccy in empty:
            return EMPTY_BOARD
        fx = FX_FIXTURE[ccy]
        base = fx * (1.01 if body["tradeType"] == "BUY" else 0.99)
        # Five ads either side of the level, so the median is exactly `base`.
        return _board([round(base * (1 + (i - 5) * 0.001), 4) for i in range(11)])
    return post


def selftest():
    # 1. parsing: real shape in, prices out; malformed degrades to []
    assert prices_from(_board([1, 2, 3])) == [1.0, 2.0, 3.0]
    assert prices_from(EMPTY_BOARD) == []
    assert prices_from({"data": [{"adv": {"price": "0"}}, {"adv": {}}, {}, "x"]}) == []
    assert prices_from({}) == [] and prices_from([]) == [] and prices_from(None) == []
    print("  [ok] board parser: prices out, malformed and empty boards -> []")

    # 2. a median needs both sides. One side alone is an asking price.
    assert summarise([10, 12, 14], [8, 9, 10]) == (12.0, 9.0, 10.5, 6)
    assert summarise([10, 12], []) == (11.0, None, None, 2)
    assert summarise([], [8, 9]) == (None, 8.5, None, 2)
    assert summarise([], []) == (None, None, None, 0)
    print("  [ok] both sides required for a mid; one side alone yields none")

    # 3. basis math and sign
    assert abs(basis_bps(1500.0, 1332.607355) - 1256.1) < 1.0     # P2P dear
    assert basis_bps(None, 1.0) is None and basis_bps(1.0, None) is None
    print("  [ok] basis sign +dear/-cheap, None-safe")

    # 4. happy path: every currency priced, BUY 1% over / SELL 1% under -> mid
    #    exactly the official rate, so basis is 0 by construction
    rows, n_ok = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE, post=_make_post())
    assert len(rows) == 10 and n_ok == 10, (len(rows), n_ok)
    by = {r["ccy"]: r for r in rows}
    assert all(r["n_ads"] == 22 for r in rows), [r["n_ads"] for r in rows]
    assert abs(by["VND"]["basis_bps"]) < 0.01, by["VND"]
    assert by["VND"]["buy_median"] > by["VND"]["sell_median"], by["VND"]
    assert set(FIELDS) >= set(rows[0])
    print("  [ok] 10/10 currencies priced; buy above sell; schema covers the row")

    # 5. an empty board is a FINDING, recorded, and does not kill the run
    rows_e, n_ok_e = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE,
                                post=_make_post(empty=("NGN", "GHS", "ETB")))
    for c in ("NGN", "GHS", "ETB"):
        r = next(x for x in rows_e if x["ccy"] == c)
        assert r["source_ok"] is False and "no ads" in r["error"], r
        assert r["mid"] is None and r["basis_bps"] is None and r["n_ads"] == 0
        assert r["fx_mid_per_usd"] is not None, "the rate we asked against is kept"
    assert n_ok_e == 7 and run_exit_code(n_ok_e) == 0
    print("  [ok] empty board -> source_ok=False row with the reason, run exits 0")

    # 6. one currency erroring isolates to its own row
    rows_o, n_ok_o = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE,
                                post=_make_post({"PKR": RuntimeError("simulated 503")}))
    pkr = next(r for r in rows_o if r["ccy"] == "PKR")
    assert pkr["source_ok"] is False and "simulated 503" in pkr["error"]
    assert n_ok_o == 9 and run_exit_code(n_ok_o) == 0
    print("  [ok] one currency erroring isolates to its own row")

    # 7. missing FX degrades only its currency
    fx_no_lbp = {k: v for k, v in FX_FIXTURE.items() if k != "LBP"}
    rows_f, _ = build_rows(TS_FIXTURE, CURRENCIES, fx_no_lbp, post=_make_post())
    lbp = next(r for r in rows_f if r["ccy"] == "LBP")
    assert lbp["source_ok"] is False and "no FX mid for LBP" in lbp["error"]
    print("  [ok] missing FX mid degrades only its currency")

    # 8. total blackout is the only non-zero exit
    dead = {c: RuntimeError("down") for c in CURRENCIES}
    rows_b, n_ok_b = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE, post=_make_post(dead))
    assert n_ok_b == 0 and all(not r["source_ok"] for r in rows_b)
    assert run_exit_code(n_ok_b) == 1
    print("  [ok] total blackout -> run exits non-zero")

    # 9. the amount filter is derived from the snapshot, not hardcoded
    seen = {}

    def spy(url, body):
        seen[body["fiat"]] = body["transAmount"]
        return EMPTY_BOARD
    build_rows(TS_FIXTURE, ["VND", "BOB"], FX_FIXTURE, post=spy)
    assert seen["VND"] == str(int(round(500 * FX_FIXTURE["VND"]))), seen
    assert seen["BOB"] == str(int(round(500 * FX_FIXTURE["BOB"]))), seen
    print(f"  [ok] amount filter is USD {FILTER_USD} converted per currency "
          f"(VND {seen['VND']}, BOB {seen['BOB']})")

    # 10. idempotency gate, same contract as the other collectors
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p2p_basis.csv")
        assert captured_this_hour(p, "ts_utc") is False, "missing file"
        now = dt.datetime(2026, 9, 2, 14, 5, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts_utc", "ccy"]).writeheader()
        assert captured_this_hour(p, "ts_utc", now) is False, "header only"
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "ccy"])
            for c in ("NGN", "EGP", "VND"):
                w.writerow({"ts_utc": "2026-09-02T13:47:00+00:00", "ccy": c})
        assert captured_this_hour(p, "ts_utc", now) is False, "prior hour"
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "ccy"])
            for c in ("NGN", "EGP", "VND"):
                w.writerow({"ts_utc": "2026-09-02T14:05:00+00:00", "ccy": c})
        assert captured_this_hour(p, "ts_utc", now) is True, "same hour"
        assert captured_this_hour(p, "ts_utc", now.replace(hour=15)) is False, "reopens"
    print("  [ok] idempotency gate: one capture per UTC hour, reopens on the next\n")

    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki P2P collector")
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

    if not a.verify and captured_this_hour(P2P, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {P2P}, nothing to do")
        return

    rows, n_ok = collect()

    # PERSIST FIRST, DISPLAY SECOND. A formatting bug must never cost a sample.
    if not a.verify:
        append(rows)

    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)

    if a.verify:
        return

    print(f"  appended -> {P2P}\n")
    if run_exit_code(n_ok) != 0:
        print("  [error] TOTAL BLACKOUT -- no currency priced this run", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
