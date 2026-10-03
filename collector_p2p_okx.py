#!/usr/bin/env python3
"""
margin.wiki P2P collector -- OKX, the second board (ROADMAP item 14).

collector_p2p.py reads one advertisement board, Binance P2P, for every
capital-controlled currency this site tracks. tools/probe_p2p_boards.py
checked Bybit, OKX and HTX live from this box on 2026-10-03 against the same
bar every collector here already meets -- no login, no API key, no CAPTCHA,
no disguised client. Bybit bot-walls every path regardless of IP; HTX answers
but publishes no mapping from its own numeric currency id to an ISO code, so
wiring it would mean guessing which country a row belongs to. OKX is the one
survivor: a live, two-sided, unauthenticated ad book, for the same method
collector_p2p.py already uses.

This is a SEPARATE file on purpose, not a second `source` value appended into
p2p_basis.csv. That file's `source` column already carries a second value
(SEB-8's NGN/coingecko fallback), but that is one currency, on hours its own
board is empty, never alongside a live primary row -- every downstream reader
of p2p_basis.csv (the evidence rule, emit_spread_signal.py, country.html's
premium) was built assuming at most one priced row per currency per hour
outside that one exception. Landing a second board for most of the currency
list into the same file would change that assumption everywhere at once,
which is a far bigger change than "a second board exists" -- and is not what
this issue asks for. This file is additive and inert: nothing reads it yet.

METHOD, same as collector_p2p.py:
  www.okx.com/v3/c2c/tradingOrders/books, GET, no auth. `side=sell` returns
  ads where the counterparty is SELLING USDT (the ask -- what a buyer of
  USDT pays); `side=buy` returns ads where the counterparty is BUYING USDT
  (the bid -- what a seller of USDT receives). Same naming as
  collector_p2p.py's buy_median/sell_median: buy_median > sell_median,
  same sign convention for basis_bps.

  basis_bps = (mid / fx_mid_local_per_usd - 1) * 10_000

OKX's endpoint takes no amount filter (`amount=500` was tried live and
changed nothing in the result set) -- unlike Binance's `transAmount`, which
the server honours directly. Each ad carries its own
`quoteMinAmountPerOrder`/`quoteMaxAmountPerOrder` range instead, so the same
FILTER_USD=500 ticket is applied here client-side: an ad only counts if that
amount, converted to local currency off the same FX snapshot, actually falls
inside the ad's own order-size range. The median is taken over the first
ROWS qualifying ads, in the order OKX returns them -- the same "top of a
realistic book" reading collector_p2p.py already uses, not every ad on the
market.

CURRENCIES is collector_p2p.py's own list, duplicated rather than imported --
same reasoning as that file's `captured_this_hour`: the two boards' layers
stay independent, so a change or a break in one cannot take down the other.
41 of these 53 price on a live run, confirmed 2026-10-03. Twelve do not, for
two distinct reasons, both recorded every run as source_ok=False with the
reason named, not folded into a single omission:
  - Four (AED, AFN, ETB, SYP) come back `{"code":17007}` from OKX -- OKX's
    own "unsupported currency" answer.
  - Eight (AOA, BDT, BND, DZD, INR, MNT, NPR, SDG) answer, but have no ask
    side at all within the FILTER_USD=500 order-size band at the moment of
    the pull -- a real, currently-empty book, not a parsing failure.

Per-currency failure isolation, one shared FX snapshot per run, exits
non-zero only on a total blackout -- the same contract as every collector in
this repo.

Usage:
  python3 collector_p2p_okx.py --verify     # one live pull, print, write nothing
  python3 collector_p2p_okx.py              # one pull, append data/p2p_okx.csv
  python3 collector_p2p_okx.py --selftest   # offline, mocked board + failures
"""

import argparse
import csv
import datetime as dt
import json
import os
import statistics
import sys
import time

try:
    import requests
except ImportError:
    requests = None

HTTP_TIMEOUT = 25
REQUEST_GAP = 0.7
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0
UA = {"User-Agent": "margin.wiki p2p-collector-okx/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
P2P = os.path.join(HERE, "data", "p2p_okx.csv")
FX_URL = "https://open.er-api.com/v6/latest/USD"
BOOKS_URL = "https://www.okx.com/v3/c2c/tradingOrders/books"
SOURCE = "okx_p2p"

UNSUPPORTED_CODE = 17007  # OKX's own "this currency has no market" answer.

FILTER_USD = 500
ROWS = 10

# Duplicated from collector_p2p.py on purpose -- see module docstring.
CURRENCIES = [
    "AED", "AFN", "AMD", "AOA", "ARS", "AZN", "BDT", "BND", "BOB", "BWP",
    "CLP", "COP", "DZD", "EGP", "ETB", "GEL", "GHS", "IDR", "INR", "IQD",
    "JOD", "KES", "KHR", "KWD", "KZT", "LAK", "LBP", "LKR", "MAD", "MNT",
    "MXN", "MZN", "NGN", "NPR", "PEN", "PHP", "PKR", "QAR", "RWF", "SAR",
    "SDG", "SYP", "TND", "TRY", "TZS", "UAH", "UGX", "VES", "VND", "XAF",
    "XOF", "ZAR", "ZMW",
]

# Confirmed live 2026-10-03: OKX's own "unsupported currency" answer, not a
# transport failure. Recorded so a currency leaving this set later is a
# visible change, not assumed permanent.
UNSUPPORTED_2026_10_03 = frozenset(["AED", "AFN", "ETB", "SYP"])

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


def _bound(x):
    """Coerce to a non-negative float, or None. Unlike `_f`, zero is a valid
    lower bound here (no minimum order size is a real ad, not a missing
    field)."""
    try:
        v = float(x)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def qualifying_prices(ads, filter_local):
    """Ads whose own min/max order size spans `filter_local` -> their prices,
    in board order. OKX has no server-side amount filter (verified live --
    `amount=500` changed nothing), so this is done here instead, over
    whatever the ad itself declares as its tradable range. An ad missing
    either bound, or a non-positive price, is dropped rather than guessed at.
    """
    out = []
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        lo = _bound(ad.get("quoteMinAmountPerOrder"))
        hi = _bound(ad.get("quoteMaxAmountPerOrder"))
        price = _f(ad.get("price"))
        if lo is None or hi is None or price is None:
            continue
        if lo <= filter_local <= hi:
            out.append(price)
    return out


def basis_bps(mid, fx_mid):
    if not mid or not fx_mid:
        return None
    return round((mid / fx_mid - 1) * 1e4, 2)


def summarise(buys, sells):
    """(buy_median, sell_median, mid, n_ads). Same rule as collector_p2p.py:
    a mid needs both sides -- one side alone is an asking price, not a
    market."""
    b = statistics.median(buys) if buys else None
    s = statistics.median(sells) if sells else None
    mid = (b + s) / 2 if (b is not None and s is not None) else None
    return b, s, mid, len(buys) + len(sells)


# ------------------------------------------------------------------ I/O
_last_call = [0.0]


def _pace():
    wait = REQUEST_GAP - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def books_url(ccy, side):
    return (f"{BOOKS_URL}?side={side}&paymentMethod=all&userType=all"
            f"&baseCurrency=usdt&quoteCurrency={ccy.lower()}"
            f"&currentPage=1&numberPerPage=20")


def get_json(url):
    """Paced, and retried on a transient failure -- same reasoning as
    collector_p2p.py's post_json: one throttled request must not cost a
    currency its row for the hour."""
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_BACKOFF * attempt)
        _pace()
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
    raise last


def fetch_fx(fetch=None):
    fetch = fetch or (lambda url: requests.get(url, timeout=HTTP_TIMEOUT, headers=UA).json())
    d = fetch(FX_URL)
    rates = d.get("rates") or {}
    if not rates:
        raise ValueError("er-api returned no rates")
    return {k: float(v) for k, v in rates.items()}


# ------------------------------------------------------------- collection
def _base_row(ts, ccy):
    return {
        "ts_utc": ts, "source": SOURCE, "ccy": ccy,
        "buy_median": None, "sell_median": None, "mid": None,
        "fx_mid_per_usd": None, "basis_bps": None, "n_ads": 0,
        "source_ok": False, "error": "",
    }


def build_rows(ts, currencies, fx, get=None):
    """One row per currency. Pure but for `get`. Returns (rows, n_ok)."""
    get = get or get_json
    rows, n_ok = [], 0
    for ccy in currencies:
        row = _base_row(ts, ccy)
        try:
            fx_mid = fx.get(ccy)
            if fx_mid is None:
                raise ValueError(f"no FX mid for {ccy}")
            row["fx_mid_per_usd"] = fx_mid
            filter_local = FILTER_USD * fx_mid

            sell_payload = get(books_url(ccy, "sell"))
            if sell_payload.get("code") == UNSUPPORTED_CODE:
                raise ValueError(f"unsupported currency (OKX code {UNSUPPORTED_CODE})")
            buy_payload = get(books_url(ccy, "buy"))
            if buy_payload.get("code") == UNSUPPORTED_CODE:
                raise ValueError(f"unsupported currency (OKX code {UNSUPPORTED_CODE})")

            # side=sell -> counterparty selling USDT -> the ASK -> buy_median
            # (what a buyer of USDT pays). side=buy -> counterparty buying
            # USDT -> the BID -> sell_median. See module docstring.
            asks = qualifying_prices((sell_payload.get("data") or {}).get("sell") or [], filter_local)
            bids = qualifying_prices((buy_payload.get("data") or {}).get("buy") or [], filter_local)
            buys, sells = asks[:ROWS], bids[:ROWS]
            b, s, mid, n = summarise(buys, sells)
            row["n_ads"] = n
            if mid is None:
                raise ValueError(
                    "no ads at ~USD %d (%d ask, %d bid)" % (FILTER_USD, len(buys), len(sells)))
            row.update(buy_median=round(b, 8), sell_median=round(s, 8),
                       mid=round(mid, 8), basis_bps=basis_bps(mid, fx_mid),
                       source_ok=True)
            n_ok += 1
        except Exception as e:
            row["error"] = f"{type(e).__name__}:{e}"[:300]
        rows.append(row)
    return rows, n_ok


def collect(currencies=CURRENCIES):
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        fx = fetch_fx()
    except Exception as e:
        print(f"  [warn] FX snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        fx = {}
    return build_rows(ts, currencies, fx)


def run_exit_code(n_ok):
    return 0 if n_ok > 0 else 1


def utc_hour(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def captured_this_hour(path, ts_field, now=None):
    """Deliberately duplicated from the other collectors -- see
    collector_p2p.py's own copy for why."""
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
    print(f"\n  USDT on OKX P2P vs official USD mid   {rows[0]['ts_utc'][:16]}Z")
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
def _book(prices, lo="1", hi="999999999"):
    return [{"price": str(p), "quoteMinAmountPerOrder": lo, "quoteMaxAmountPerOrder": hi}
            for p in prices]


EMPTY_PAYLOAD = {"code": 0, "data": {"sell": [], "buy": []}}
UNSUPPORTED_PAYLOAD = {"code": UNSUPPORTED_CODE, "data": {}}
FX_FIXTURE = {
    "AED": 3.6725, "AFN": 64.838212, "AMD": 363.830153, "AOA": 931.930703,
    "ARS": 1507.3745, "AZN": 1.699716, "BDT": 122.859412, "BND": 1.266802,
    "BOB": 12.145708, "BWP": 13.688252, "CLP": 932.412272, "COP": 3152.90844,
    "DZD": 133.338687, "EGP": 50.944245, "ETB": 162.347477, "GEL": 2.613051,
    "GHS": 11.363793, "IDR": 17674.218391, "INR": 94.51761,
    "IQD": 1311.094196, "JOD": 0.709, "KES": 129.388213, "KHR": 4045.073099,
    "KWD": 0.308726, "KZT": 455.771483, "LAK": 22199.314709, "LBP": 89500,
    "LKR": 328.202304, "MAD": 9.348756, "MNT": 3557.475045, "MXN": 16.894736,
    "MZN": 63.818874, "NGN": 1324.205782, "NPR": 151.228136, "PEN": 3.360932,
    "PHP": 62.696582, "PKR": 277.597405, "QAR": 3.64, "RWF": 1476.188744,
    "SAR": 3.75, "SDG": 510.232995, "SYP": 121.840777, "TND": 2.90854,
    "TRY": 48.416604, "TZS": 2641.564042, "UAH": 44.598868,
    "UGX": 3716.890981, "VES": 813.7361, "VND": 26025.122751,
    "XAF": 564.855203, "XOF": 564.855203, "ZAR": 15.966228, "ZMW": 19.110335,
}
TS_FIXTURE = "2026-10-03T00:00:00+00:00"


def _make_get(overrides=None, unsupported=()):
    """Fake books: sell (ask) 1% over the official rate, buy (bid) 1% under,
    every ad's own range wide enough to always qualify."""
    overrides = overrides or {}

    def get(url):
        ccy = url.split("quoteCurrency=")[1].split("&")[0].upper()
        side = "sell" if "side=sell" in url else "buy"
        key = (ccy, side)
        if key in overrides:
            val = overrides[key]
            if isinstance(val, Exception):
                raise val
            return val
        if ccy in unsupported:
            return UNSUPPORTED_PAYLOAD
        fx = FX_FIXTURE[ccy]
        base = fx * (1.01 if side == "sell" else 0.99)
        # ROWS prices symmetric around `base`, so slicing to the first ROWS
        # (as build_rows does) keeps the median exactly `base`.
        offsets = [i - (ROWS - 1) / 2 for i in range(ROWS)]
        prices = [round(base * (1 + off * 0.001), 4) for off in offsets]
        return {"code": 0, "data": {side: _book(prices)}}
    return get


def selftest():
    # 1. qualifying_prices: in range keeps, out of range drops, missing bound
    #    or bad price drops -- never a guess.
    ads = [{"price": "100", "quoteMinAmountPerOrder": "0", "quoteMaxAmountPerOrder": "1000"},
           {"price": "200", "quoteMinAmountPerOrder": "5000", "quoteMaxAmountPerOrder": "9000"},
           {"price": "300"},
           {"price": "0", "quoteMinAmountPerOrder": "0", "quoteMaxAmountPerOrder": "1000"},
           "not a dict"]
    assert qualifying_prices(ads, 500) == [100.0]
    assert qualifying_prices([], 500) == []
    print("  [ok] qualifying_prices: in-range kept, out-of-range/missing/bad dropped")

    # 2. a median needs both sides.
    assert summarise([10, 12, 14], [8, 9, 10]) == (12.0, 9.0, 10.5, 6)
    assert summarise([10, 12], []) == (11.0, None, None, 2)
    assert summarise([], []) == (None, None, None, 0)
    print("  [ok] both sides required for a mid; one side alone yields none")

    # 3. basis math and sign, same convention as collector_p2p.py
    assert abs(basis_bps(1500.0, 1332.607355) - 1256.1) < 1.0
    assert basis_bps(None, 1.0) is None and basis_bps(1.0, None) is None
    print("  [ok] basis sign +dear/-cheap, None-safe")

    # 4. happy path: every currency priced, ask 1% over / bid 1% under ->
    #    mid exactly the official rate, basis 0 by construction
    rows, n_ok = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE, get=_make_get())
    assert len(rows) == len(CURRENCIES) == 53
    assert n_ok == 53, n_ok
    by = {r["ccy"]: r for r in rows}
    assert abs(by["VND"]["basis_bps"]) < 0.01, by["VND"]
    assert by["VND"]["buy_median"] > by["VND"]["sell_median"], by["VND"]
    public = {k for k in rows[0]}
    assert set(FIELDS) == public, public ^ set(FIELDS)
    print(f"  [ok] {n_ok}/{len(CURRENCIES)} currencies priced; buy above sell; "
          f"schema matches FIELDS exactly")

    # 4b. the amount filter is local-currency, derived from the FX snapshot
    seen = []

    def spy(url):
        seen.append(url)
        return {"code": 0, "data": {"sell": _book([100]), "buy": _book([99])}}
    build_rows(TS_FIXTURE, ["VND"], FX_FIXTURE, get=spy)
    assert any("quoteCurrency=vnd" in u for u in seen), seen
    print("  [ok] request targets the right OKX quoteCurrency per call")

    # 5. OKX's own unsupported-currency code isolates to that currency, with
    #    the real reason, not a generic transport error.
    rows_u, n_ok_u = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE,
                                get=_make_get(unsupported=UNSUPPORTED_2026_10_03))
    for c in UNSUPPORTED_2026_10_03:
        r = next(x for x in rows_u if x["ccy"] == c)
        assert r["source_ok"] is False and "17007" in r["error"], r
    assert n_ok_u == 53 - len(UNSUPPORTED_2026_10_03), n_ok_u
    assert run_exit_code(n_ok_u) == 0
    print("  [ok] OKX's own unsupported-currency code isolates to its row, "
          "named, not swallowed as a generic failure")

    # 6. an empty book (code 0, no ads either side) is a finding, not a crash
    rows_e, n_ok_e = build_rows(TS_FIXTURE, ["BDT"], FX_FIXTURE,
                                get=lambda url: EMPTY_PAYLOAD)
    assert rows_e[0]["source_ok"] is False and "no ads" in rows_e[0]["error"]
    assert n_ok_e == 0 and run_exit_code(n_ok_e) == 1
    print("  [ok] an empty book (no ads either side) -> source_ok=False, "
          "and an all-empty run exits non-zero")

    # 7. one currency erroring isolates to its own row
    rows_o, n_ok_o = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE,
                                get=_make_get({("PKR", "sell"): RuntimeError("simulated 503")}))
    pkr = next(r for r in rows_o if r["ccy"] == "PKR")
    assert pkr["source_ok"] is False and "simulated 503" in pkr["error"]
    assert n_ok_o == 52 and run_exit_code(n_ok_o) == 0
    print("  [ok] one currency erroring isolates to its own row")

    # 8. missing FX degrades only its currency
    fx_no_lbp = {k: v for k, v in FX_FIXTURE.items() if k != "LBP"}
    rows_f, _ = build_rows(TS_FIXTURE, CURRENCIES, fx_no_lbp, get=_make_get())
    lbp = next(r for r in rows_f if r["ccy"] == "LBP")
    assert lbp["source_ok"] is False and "no FX mid for LBP" in lbp["error"]
    print("  [ok] missing FX mid degrades only its currency")

    # 9. total blackout is the only non-zero exit
    get_dead = lambda url: (_ for _ in ()).throw(RuntimeError("down"))
    rows_b, n_ok_b = build_rows(TS_FIXTURE, CURRENCIES, FX_FIXTURE, get=get_dead)
    assert n_ok_b == 0 and all(not r["source_ok"] for r in rows_b)
    assert run_exit_code(n_ok_b) == 1
    print("  [ok] total blackout -> run exits non-zero")

    # 10. pacing is real
    assert REQUEST_GAP > 0 and RETRY_ATTEMPTS >= 2
    t0 = time.monotonic(); _pace(); _pace(); _pace()
    held = time.monotonic() - t0
    assert held >= REQUEST_GAP * 2 - 0.05, held
    print(f"  [ok] transport paces {REQUEST_GAP}s between calls")

    # 11. idempotency gate, same contract as the other collectors
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "p2p_okx.csv")
        assert captured_this_hour(p, "ts_utc") is False, "missing file"
        now = dt.datetime(2026, 10, 3, 14, 5, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts_utc", "ccy"]).writeheader()
        assert captured_this_hour(p, "ts_utc", now) is False, "header only"
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "ccy"])
            w.writerow({"ts_utc": "2026-10-03T14:05:00+00:00", "ccy": "NGN"})
        assert captured_this_hour(p, "ts_utc", now) is True, "same hour"
        assert captured_this_hour(p, "ts_utc", now.replace(hour=15)) is False, "reopens"
    print("  [ok] idempotency gate: one capture per UTC hour, reopens on the next\n")

    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki P2P collector -- OKX")
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
