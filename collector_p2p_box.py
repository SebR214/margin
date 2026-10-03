#!/usr/bin/env python3
"""
margin.wiki P2P collector -- the BOX layer (ROADMAP item 12, SEB-202).

collector_p2p.py reads Binance P2P hourly, from a US GitHub Actions runner,
against a hand-written list of 53 currencies, ten ads a side. This is the same
board, read differently, from this box (Hetzner, Falkenstein DE):

  - every ten minutes, not every hour
  - every currency the FX snapshot itself carries a rate for, not a
    hand-picked 53 -- see "Enumeration" below for why this, and not a
    Binance-published list, is the live universe
  - the full first page (20 ads, the server's own maximum -- 21 is rejected
    with its own "illegal parameter" code, confirmed live 2026-10-03), not ten
  - order-book DEPTH at the five ladder amounts (collector_providers.py's own
    LADDER: 200/1,000/5,000/25,000/50,000, in USD converted per currency off
    the same FX snapshot), not a single median at one filter size

Enumeration. Binance P2P publishes no login-free endpoint that lists its own
supported fiat currencies -- every path this file's author tried under
p2p.binance.com/bapi/c2c (portal/config, filter-conditions, fiat/list,
currency/list, and permutations) either 404s or answers only for the fiat it
already assumes from the caller's own IP geolocation. Worse: the search
endpoint itself cannot tell a real-but-currently-quiet currency from a fiat
code that does not exist at all -- `fiat=ZZZ` and `fiat=BOB` (a real, thin
market) come back byte-identical (`total:0, data:[]`), confirmed live. There is
no way to ask Binance "what currencies do you list" without inventing an
answer it cannot actually give.

The honest substitute: `fetch_fx()` -- the same open.er-api.com call
collector_p2p.py already makes every run -- returns a rate for every real
circulating currency it tracks (166 on 2026-10-03, a live, third-party,
non-hand-picked list). This file asks about every one of those (minus USD
itself, a degenerate self-pair -- pricing USDT against the dollar it already
is tells nothing about dollar access). A currency this probes that turns out
to have no live board (an IMF unit like XDR, an indexed accounting unit like
CLF, or simply a market Binance never listed) is not special-cased out --
it lands exactly like NGN/GHS/ETB already do in collector_p2p.py: a permanent,
visible, source_ok=False row with the reason, never omitted, never invented.
"Enumerated live" here means asking a live, independent, non-curated list,
not that Binance confirms the list itself -- it cannot.

RAW VS PUBLISHED. Every ad on the fetched page is real data this run is not
entitled to discard, but it is also far too much to commit: ~165 currencies x
up to 20 ads x 2 sides, every ten minutes, is not something `data/` (git,
history forever) should carry. So two separate things happen to the same
page:

  RAW   every parsed ad, verbatim fields, written to a small parquet file
        under this box's own state directory (BOX_STATE_DIR, default
        /var/lib/margin/p2p_box/raw/<YYYY-MM>/<slot>.parquet) -- one file per
        ten-minute pass, never rewritten, so a month's worth is one DuckDB
        `read_parquet('YYYY-MM/*.parquet')` away without ever re-writing old
        data. OUTSIDE every git checkout on this box. Never committed, by
        construction -- there is no code path from this file to `git`.

  PUBLISHED   one row per (ts_utc, ccy): ad counts, real total depth, and
        n/median-price at each of the five ladder amounts, each side. Small
        enough for `data/`. Staged to BOX_STATE_DIR/published_depth.csv (also
        outside any checkout -- the agent-role checkouts switch branches
        constantly and the served checkout is hard-reset every five minutes by
        margin-pull.timer; neither is a safe place for a long-lived append-only
        file this collector owns). `tools/publish_p2p_box.py` is the seam: it
        copies staged rows into `data/p2p_box_depth.csv` and computes the
        dated baseline, and it runs as an ordinary step of an ordinary
        reviewed PR -- see that file's docstring for why this does NOT push to
        `main` on its own. Once a row is copied into `data/`, it reaches the
        site the same way every other collector's row does: through
        `tools/emit_bundle.py`, which already globs every `data/*.csv` into the
        DuckDB-queryable bundle with no changes needed here.

DISK. Collection stops loudly, before a single request, if the filesystem
under BOX_STATE_DIR is at or past DISK_STOP_PCT (80%) full -- see `disk_ok()`.
Not a soft warning: no request goes out and nothing is written that pass.

PACING. Same transport shape as collector_p2p.py (serial, paced, retried,
exits non-zero only on a total blackout), plus jitter on top of the base gap
-- ROADMAP item 12 asks for "jitter and backoff" distinctly from the hourly
layer's fixed gap, so this file's own REQUEST_GAP carries a random component
collector_p2p.py's does not. Own named User-Agent, never Binance's own site
UA, never a session cookie.

RESOURCE CAPS. This file does not set its own cgroup limits -- that is
`agents/systemd/margin-p2p-box.service`'s job (CPUWeight, IOWeight, MemoryMax),
kept low relative to the three agent-loop services so a 10-minute HTTP pass
can never compete with a running model turn for the box's CPU.

Usage:
  python3 collector_p2p_box.py --verify     # one live pull, print, write nothing
  python3 collector_p2p_box.py              # one pass, stage + raw-parquet
  python3 collector_p2p_box.py --selftest   # offline, mocked board + failures
"""

import argparse
import csv
import datetime as dt
import json
import os
import random
import statistics
import sys
import time

try:
    import requests
except ImportError:
    requests = None

try:
    import duckdb
except ImportError:
    duckdb = None

HTTP_TIMEOUT = 25
# Base gap matches collector_p2p.py's own measured safe pace (0.7s, survived a
# 2026-09-05 parallel-request rate limit where 8-wide did not). The jitter on
# top is this file's own addition -- ROADMAP item 12 asks for it distinctly
# from the hourly layer, and it is cheap insurance against this run looking
# like a metronome to whatever is watching request timing on the other end.
REQUEST_GAP = 0.7
REQUEST_JITTER = 0.3
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0
UA = {"User-Agent": "margin.wiki p2p-box-collector/1.0 (+https://margin.wiki)",
      "content-type": "application/json"}

HERE = os.path.dirname(os.path.abspath(__file__))
FX_URL = "https://open.er-api.com/v6/latest/USD"
SEARCH_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
SOURCE = "binance_p2p_box"

# The server's own page-size ceiling: rows=21 answers code 000002 "illegal
# parameter", rows<=20 does not -- confirmed live 2026-10-03. Not a guess.
ROWS = 20

# Same ladder every deep-layer collector in this repo already uses
# (collector_providers.py's own LADDER). Duplicated, not imported -- this
# file's layer stays independent of the deep layer's, same reasoning every
# sibling P2P collector here already gives for its own duplication.
LADDER_USD = [200, 1000, 5000, 25000, 50000]

SLOT_MINUTES = 10
DISK_STOP_PCT = 80

# Everything this file owns lives here, outside every git checkout on the box
# -- see the module docstring, "RAW VS PUBLISHED". Overridable so tests (and a
# by-hand run) never touch the real box state.
BOX_STATE_DIR = os.environ.get("MARGIN_BOX_STATE_DIR",
                                "/var/lib/margin/p2p_box")


def raw_dir(state_dir=BOX_STATE_DIR):
    return os.path.join(state_dir, "raw")


def published_stage_path(state_dir=BOX_STATE_DIR):
    return os.path.join(state_dir, "published_depth.csv")


def lock_path(state_dir=BOX_STATE_DIR):
    return os.path.join(state_dir, ".lock")


def _ladder_field(amount, side, suffix):
    return f"depth_{amount}_{side}_{suffix}"


PUBLISHED_FIELDS = ["ts_utc", "source", "ccy", "n_ads_buy", "n_ads_sell",
                    "total_buy", "total_sell"]
for _amt in LADDER_USD:
    for _side in ("buy", "sell"):
        PUBLISHED_FIELDS.append(_ladder_field(_amt, _side, "n"))
        PUBLISHED_FIELDS.append(_ladder_field(_amt, _side, "price"))
PUBLISHED_FIELDS += ["source_ok", "error"]

RAW_FIELDS = ["ts_utc", "ccy", "side", "adv_no", "price", "min_amt", "max_amt",
              "surplus_amount", "tradable_quantity"]


# ------------------------------------------------------------- pure core
def _f(x):
    """Coerce to a positive float, or None. Prices come back as strings."""
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _bound(x):
    """Coerce to a non-negative float, or None -- zero is a valid lower
    bound (no minimum order size is a real ad), unlike `_f`."""
    try:
        v = float(x)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def parse_ads(payload):
    """Ad-board payload -> list of {price, min_amt, max_amt, surplus,
    tradable, adv_no} dicts, in board order. Anything without a usable price
    is dropped, same rule as every sibling collector's `prices_from`."""
    if not isinstance(payload, dict):
        return []
    out = []
    for row in (payload.get("data") or []):
        if not isinstance(row, dict):
            continue
        adv = row.get("adv") or {}
        price = _f(adv.get("price"))
        if price is None:
            continue
        out.append({
            "price": price,
            "min_amt": _bound(adv.get("minSingleTransAmount")),
            "max_amt": _bound(adv.get("maxSingleTransAmount")),
            "surplus": _bound(adv.get("surplusAmount")),
            "tradable": _bound(adv.get("tradableQuantity")),
            "adv_no": adv.get("advNo"),
        })
    return out


def total_from(payload):
    """Binance's own `total` -- real depth behind the whole search, not just
    the fetched page. None (a gap, never a false 0) if missing or unreadable.
    Identical contract to collector_p2p.py's own `total_from` (SEB-50)."""
    if not isinstance(payload, dict):
        return None
    t = payload.get("total")
    if isinstance(t, bool):
        return None
    try:
        v = int(t)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def depth_at(ads, amount_local):
    """(n qualifying, median price) among `ads` whose own min/max single-
    transaction bounds admit `amount_local` -- same client-side qualification
    collector_p2p_okx.py's `qualifying_prices` already uses for its one fixed
    filter size, generalised here to an arbitrary amount. An ad missing
    either bound cannot be shown to qualify, so it is excluded rather than
    guessed into or out of the ladder rung."""
    qualifying = [a["price"] for a in ads
                  if a["min_amt"] is not None and a["max_amt"] is not None
                  and a["min_amt"] <= amount_local <= a["max_amt"]]
    if not qualifying:
        return 0, None
    return len(qualifying), round(statistics.median(qualifying), 8)


def basis_bps(mid, fx_mid):
    if not mid or not fx_mid:
        return None
    return round((mid / fx_mid - 1) * 1e4, 2)


def currencies_from_fx(fx):
    """Every real currency the FX snapshot itself carries, minus USD -- see
    the module docstring, "Enumeration", for why this and not a hand-picked
    or Binance-confirmed list is the live universe asked about."""
    return sorted(c for c in fx if c != "USD")


# ------------------------------------------------------------------ I/O
_last_call = [0.0]


def _pace():
    """Hold REQUEST_GAP plus jitter between outbound calls."""
    gap = REQUEST_GAP + random.uniform(0, REQUEST_JITTER)
    wait = gap - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def post_json(url, body):
    """Paced, retried on a transient failure -- same contract as every
    sibling collector's transport: one throttled request must not cost a
    currency its row for the slot."""
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_BACKOFF * attempt)
        _pace()
        try:
            r = requests.post(url, json=body, timeout=HTTP_TIMEOUT, headers=UA)
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


def search_body(ccy, trade_type):
    """No `transAmount` key -- confirmed live 2026-10-03 that omitting it
    returns the real unfiltered top of book (e.g. VND: total=458 with no
    filter vs total=0 the instant any `transAmount` is set, including "1").
    Passing a size here would silently exclude ads whose own range cannot
    serve it, which is exactly backwards for a file whose job is to measure
    depth AT five different sizes from the same page."""
    return {"page": 1, "rows": ROWS, "asset": "USDT", "fiat": ccy,
            "tradeType": trade_type, "payTypes": [], "publisherType": None}


# ------------------------------------------------------------- collection
def _base_row(ts, ccy):
    row = {"ts_utc": ts, "source": SOURCE, "ccy": ccy,
           "n_ads_buy": 0, "n_ads_sell": 0, "total_buy": None, "total_sell": None,
           "source_ok": False, "error": ""}
    for amt in LADDER_USD:
        for side in ("buy", "sell"):
            row[_ladder_field(amt, side, "n")] = 0
            row[_ladder_field(amt, side, "price")] = None
    return row


def build_rows(ts, currencies, fx, post=post_json):
    """One summary row and a handful of raw-ad rows per currency. Pure but
    for `post`. Returns (summary_rows, raw_rows, n_ok) -- per-currency failure
    isolation and a total-blackout-only non-zero exit, same contract as every
    collector in this repo."""
    summary_rows, raw_rows, n_ok = [], [], 0
    for ccy in currencies:
        row = _base_row(ts, ccy)
        try:
            fx_mid = fx.get(ccy)
            if fx_mid is None:
                raise ValueError(f"no FX mid for {ccy}")

            buy_payload = post(SEARCH_URL, search_body(ccy, "BUY"))
            sell_payload = post(SEARCH_URL, search_body(ccy, "SELL"))
            buy_ads = parse_ads(buy_payload)
            sell_ads = parse_ads(sell_payload)
            row["n_ads_buy"], row["n_ads_sell"] = len(buy_ads), len(sell_ads)
            row["total_buy"], row["total_sell"] = total_from(buy_payload), total_from(sell_payload)

            if not buy_ads and not sell_ads:
                raise ValueError("no ads on the first page, either side")

            for amt in LADDER_USD:
                local = amt * fx_mid
                n_b, p_b = depth_at(buy_ads, local)
                n_s, p_s = depth_at(sell_ads, local)
                row[_ladder_field(amt, "buy", "n")] = n_b
                row[_ladder_field(amt, "buy", "price")] = p_b
                row[_ladder_field(amt, "sell", "n")] = n_s
                row[_ladder_field(amt, "sell", "price")] = p_s

            row["source_ok"] = True
            n_ok += 1

            for a in buy_ads:
                raw_rows.append({"ts_utc": ts, "ccy": ccy, "side": "buy",
                                  "adv_no": a["adv_no"], "price": a["price"],
                                  "min_amt": a["min_amt"], "max_amt": a["max_amt"],
                                  "surplus_amount": a["surplus"], "tradable_quantity": a["tradable"]})
            for a in sell_ads:
                raw_rows.append({"ts_utc": ts, "ccy": ccy, "side": "sell",
                                  "adv_no": a["adv_no"], "price": a["price"],
                                  "min_amt": a["min_amt"], "max_amt": a["max_amt"],
                                  "surplus_amount": a["surplus"], "tradable_quantity": a["tradable"]})
        except Exception as e:
            row["error"] = f"{type(e).__name__}:{e}"[:300]
        summary_rows.append(row)
    return summary_rows, raw_rows, n_ok


def collect(currencies=None):
    """One live sample. Never raises; records failures. `currencies=None`
    means "ask fetch_fx() what exists" -- the live default this file is for;
    tests pass an explicit list instead."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        fx = fetch_fx()
    except Exception as e:
        print(f"  [warn] FX snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        fx = {}
    ccys = currencies if currencies is not None else currencies_from_fx(fx)
    return build_rows(ts, ccys, fx)


def run_exit_code(n_ok):
    return 0 if n_ok > 0 else 1


# --------------------------------------------------------- disk + slot gate
def disk_ok(path, stop_pct=DISK_STOP_PCT, usage=None):
    """(ok, used_pct) for the filesystem under `path`. Collection stops
    loudly, before any request, at or past `stop_pct` -- never a silent
    throttle. `usage` is an injection point for tests
    (shutil.disk_usage-shaped: total/used/free)."""
    import shutil
    os.makedirs(path, exist_ok=True)
    total, used, _free = usage if usage is not None else shutil.disk_usage(path)
    pct = (used / total * 100.0) if total else 0.0
    return pct < stop_pct, round(pct, 1)


def utc_slot(now=None):
    """Floor to the SLOT_MINUTES boundary -- same role as collector_p2p.py's
    `utc_hour`, at ten-minute resolution instead of one."""
    n = now or dt.datetime.now(dt.timezone.utc)
    floored_minute = (n.minute // SLOT_MINUTES) * SLOT_MINUTES
    return n.replace(minute=floored_minute, second=0, microsecond=0)


def captured_this_slot(path, ts_field, now=None):
    """True if `path` already holds a row stamped in the current ten-minute
    slot. Deliberately duplicated from the hourly collectors' own
    `captured_this_hour` -- same reasoning: these layers stay
    import-independent so a break in one cannot take down another."""
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
    return utc_slot(t.astimezone(dt.timezone.utc)) == utc_slot(now)


# ------------------------------------------------------------------ write
def write_published_stage(rows, state_dir=BOX_STATE_DIR):
    path = published_stage_path(state_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PUBLISHED_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return path


def write_raw_parquet(rows, ts, state_dir=BOX_STATE_DIR):
    """Every parsed ad this pass saw, to its own file -- never a rewrite of
    an existing one. One DuckDB table, built in memory from plain INSERTs (no
    pandas needed), copied out as parquet. Returns the path written, or None
    if there were no ads to write (nothing to record raw, same as a page with
    no ads contributing no rows to data/p2p_offers.csv in the hourly layer)."""
    if not rows:
        return None
    if duckdb is None:
        raise RuntimeError("duckdb is required to write the raw layer -- see requirements.txt")
    month_dir = os.path.join(raw_dir(state_dir), ts[:7])
    os.makedirs(month_dir, exist_ok=True)
    fname = ts.replace(":", "").replace("+00:00", "Z").replace(".", "_") + ".parquet"
    path = os.path.join(month_dir, fname)
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE raw (ts_utc VARCHAR, ccy VARCHAR, side VARCHAR, "
            "adv_no VARCHAR, price DOUBLE, min_amt DOUBLE, max_amt DOUBLE, "
            "surplus_amount DOUBLE, tradable_quantity DOUBLE)"
        )
        con.executemany(
            "INSERT INTO raw VALUES (?,?,?,?,?,?,?,?,?)",
            [tuple(r[f] for f in RAW_FIELDS) for r in rows],
        )
        con.execute("COPY raw TO ? (FORMAT PARQUET)", [path])
    finally:
        con.close()
    return path


# --------------------------------------------------------------- lockfile
def acquire_lock(state_dir=BOX_STATE_DIR):
    """A stale-or-crashed previous pass must not wedge every pass after it --
    a pidfile whose pid is no longer alive is treated as stale and replaced.
    Returns True if the lock is ours, False (loud, on stderr by the caller)
    if a live pass genuinely still holds it."""
    path = lock_path(state_dir)
    os.makedirs(state_dir, exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            return False  # still alive
        except (ValueError, OSError):
            pass  # unreadable or dead -- stale, ours to take
    with open(path, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock(state_dir=BOX_STATE_DIR):
    try:
        os.remove(lock_path(state_dir))
    except OSError:
        pass


# ------------------------------------------------------------------ print
def print_table(rows):
    print(f"\n  USDT on Binance P2P (box layer) vs official USD mid   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 78)
    print(f"  {'CCY':<5}{'ADS(B/S)':>10}{'TOTAL(B/S)':>14}"
          + "".join(f"{('D'+str(a)):>10}" for a in LADDER_USD))
    print("  " + "-" * 78)
    for r in rows:
        depths = " ".join(
            f"{r[_ladder_field(a, 'buy', 'n')]}/{r[_ladder_field(a, 'sell', 'n')]}".rjust(9)
            for a in LADDER_USD)
        print(f"  {r['ccy']:<5}{str(r['n_ads_buy']) + '/' + str(r['n_ads_sell']):>10}"
              f"{str(r['total_buy']) + '/' + str(r['total_sell']):>14} {depths}")
    print("  " + "-" * 78)
    bad = [r for r in rows if not r["source_ok"]]
    for r in bad[:10]:
        print(f"  ! {r['ccy']}: {r['error']}")
    if len(bad) > 10:
        print(f"  ... and {len(bad) - 10} more absent currencies")
    print(f"  {len(rows) - len(bad)}/{len(rows)} currencies answered"
          f"{' -- TOTAL BLACKOUT' if len(bad) == len(rows) else ''}\n")


# -------------------------------------------------------------- selftest
def _ad(price, lo="1", hi="999999999", surplus="1000", tradable="1000", adv_no="x"):
    return {"adv": {"advNo": adv_no, "price": str(price),
                    "minSingleTransAmount": lo, "maxSingleTransAmount": hi,
                    "surplusAmount": surplus, "tradableQuantity": tradable}}


def _board(ads, total=None):
    return {"code": "000000", "success": True,
            "total": len(ads) if total is None else total, "data": ads}


EMPTY_BOARD = {"code": "000000", "success": True, "data": [], "total": 0}
FX_FIXTURE = {
    "VND": 26025.122751, "NGN": 1324.205782, "BOB": 12.145708,
    "PKR": 277.597405, "LBP": 89500, "USD": 1.0,
}
TS_FIXTURE = "2026-10-03T00:00:00+00:00"


def selftest():
    # 1. enumeration: every real FX key except USD, live each run.
    assert currencies_from_fx(FX_FIXTURE) == ["BOB", "LBP", "NGN", "PKR", "VND"]
    print("  [ok] currencies_from_fx: every FX-rated currency, USD excluded, sorted")

    # 2. ad parsing: real shape in, bounds and price out; malformed dropped.
    ads = parse_ads(_board([_ad(100, "10", "1000"), {"adv": {"price": "0"}}, {"adv": {}}, "x"]))
    assert len(ads) == 1 and ads[0]["price"] == 100.0 and ads[0]["min_amt"] == 10.0
    assert parse_ads(EMPTY_BOARD) == [] and parse_ads(None) == [] and parse_ads({}) == []
    print("  [ok] parse_ads: real ad kept with its bounds, malformed/empty -> []")

    # 2b. total_from -- same contract as collector_p2p.py's own (SEB-50).
    assert total_from(_board([_ad(1)], total=458)) == 458
    assert total_from({"data": []}) is None, "missing field is a gap, never 0"
    assert total_from({"data": [], "total": -1}) is None
    print("  [ok] total_from: real depth out, unreadable/missing -> None (never 0)")

    # 3. depth_at: only ads whose own range admits the amount qualify; the
    #    median is over qualifying ads only, and an ad missing a bound never
    #    qualifies by assumption.
    ads = [
        {"price": 100.0, "min_amt": 0.0, "max_amt": 50.0},
        {"price": 110.0, "min_amt": 0.0, "max_amt": 50000.0},
        {"price": 120.0, "min_amt": 20000.0, "max_amt": 60000.0},
        {"price": 999.0, "min_amt": None, "max_amt": None},
    ]
    assert depth_at(ads, 10) == (2, 105.0)      # first two admit a $10 ticket
    assert depth_at(ads, 30000) == (2, 115.0)   # the $50k-max and $20k-60k ads
    assert depth_at(ads, 1_000_000) == (0, None)
    print("  [ok] depth_at: only ads whose own bounds admit the ladder amount "
          "qualify, median over those only")

    # 4. basis sign, None-safe.
    assert abs(basis_bps(1500.0, 1332.607355) - 1256.1) < 1.0
    assert basis_bps(None, 1.0) is None and basis_bps(1.0, None) is None
    print("  [ok] basis sign +dear/-cheap, None-safe")

    # 5. search_body carries no transAmount key -- confirmed live 2026-10-03
    #    that adding one (even "1") collapses VND's real total=458 book to 0.
    body = search_body("VND", "BUY")
    assert "transAmount" not in body, body
    assert body["rows"] == ROWS == 20
    print(f"  [ok] search_body: no transAmount key, rows={ROWS} "
          f"(the server's own page-size ceiling)")

    # 6. happy path: every currency answers, both sides, depth computed at
    #    every ladder size; raw rows carry one entry per fetched ad.
    def post_ok(url, body):
        base = FX_FIXTURE[body["fiat"]] * (1.01 if body["tradeType"] == "BUY" else 0.99)
        ads = [_ad(round(base * (1 + (i - 3) * 0.001), 4), "0", "999999999")
               for i in range(5)]
        return _board(ads, total=458)
    summary, raw, n_ok = build_rows(TS_FIXTURE, currencies_from_fx(FX_FIXTURE), FX_FIXTURE, post=post_ok)
    assert n_ok == 5 and len(summary) == 5
    by = {r["ccy"]: r for r in summary}
    assert by["VND"]["source_ok"] is True and by["VND"]["n_ads_buy"] == 5
    assert by["VND"]["total_buy"] == 458
    assert by["VND"][_ladder_field(200, "buy", "n")] == 5, "wide bounds qualify at every ladder size"
    assert set(PUBLISHED_FIELDS) >= set(by["VND"]), set(by["VND"]) - set(PUBLISHED_FIELDS)
    assert len(raw) == 5 * 5 * 2, "5 currencies x 5 ads x 2 sides"
    assert set(RAW_FIELDS) == {r for r in raw[0]}
    print(f"  [ok] happy path: {n_ok}/5 currencies, depth computed at all "
          f"{len(LADDER_USD)} ladder sizes, {len(raw)} raw ad rows kept")

    # 7. one currency erroring isolates to its own row; a currency with no FX
    #    mid degrades only itself; a board with ads on neither side is a
    #    recorded absence, not skipped.
    def post_mixed(url, body):
        if body["fiat"] == "PKR":
            raise RuntimeError("simulated 503")
        if body["fiat"] == "LBP":
            return EMPTY_BOARD
        return post_ok(url, body)
    summary_m, _, n_ok_m = build_rows(TS_FIXTURE, currencies_from_fx(FX_FIXTURE), FX_FIXTURE, post=post_mixed)
    by_m = {r["ccy"]: r for r in summary_m}
    assert by_m["PKR"]["source_ok"] is False and "simulated 503" in by_m["PKR"]["error"]
    assert by_m["LBP"]["source_ok"] is False and "no ads" in by_m["LBP"]["error"]
    assert n_ok_m == 3, n_ok_m
    assert run_exit_code(n_ok_m) == 0
    fx_no_bob = {k: v for k, v in FX_FIXTURE.items() if k != "BOB"}
    summary_f, _, _ = build_rows(TS_FIXTURE, currencies_from_fx(FX_FIXTURE), fx_no_bob, post=post_ok)
    bob = next(r for r in summary_f if r["ccy"] == "BOB")
    assert bob["source_ok"] is False and "no FX mid for BOB" in bob["error"]
    print("  [ok] one currency erroring, an empty board, and a missing FX mid "
          "each isolate to their own row -- never skipped, never fabricated")

    # 8. total blackout is the only non-zero exit.
    def post_dead(url, body):
        raise RuntimeError("down")
    _, _, n_ok_b = build_rows(TS_FIXTURE, currencies_from_fx(FX_FIXTURE), FX_FIXTURE, post=post_dead)
    assert n_ok_b == 0 and run_exit_code(n_ok_b) == 1
    print("  [ok] total blackout -> run exits non-zero")

    # 9. disk stop: at or past DISK_STOP_PCT, loud and false; under it, true.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ok, pct = disk_ok(d, usage=(100, 79, 21))
        assert ok is True and pct == 79.0
        ok, pct = disk_ok(d, usage=(100, 80, 20))
        assert ok is False and pct == 80.0, "at the threshold stops, not just past it"
        ok, pct = disk_ok(d, usage=(100, 95, 5))
        assert ok is False and pct == 95.0
    print(f"  [ok] disk_ok: stops at or past {DISK_STOP_PCT}%, continues under it")

    # 10. pacing holds the base gap plus jitter between calls, never less
    #     than the base gap alone.
    t0 = time.monotonic(); _pace(); _pace(); _pace()
    held = time.monotonic() - t0
    assert held >= REQUEST_GAP * 2 - 0.05, held
    print(f"  [ok] transport paces >= {REQUEST_GAP}s plus up to {REQUEST_JITTER}s jitter between calls")

    # 11. slot gate: one capture per ten-minute slot, reopens on the next,
    #     same mechanics as the hourly collectors' own gate.
    import tempfile as tf
    with tf.TemporaryDirectory() as d:
        p = os.path.join(d, "published_depth.csv")
        assert captured_this_slot(p, "ts_utc") is False, "missing file"
        now = dt.datetime(2026, 10, 3, 14, 23, tzinfo=dt.timezone.utc)
        assert utc_slot(now) == dt.datetime(2026, 10, 3, 14, 20, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts_utc", "ccy"]).writeheader()
        assert captured_this_slot(p, "ts_utc", now) is False, "header only"
        with open(p, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts_utc", "ccy"]).writerow(
                {"ts_utc": "2026-10-03T14:21:00+00:00", "ccy": "VND"})
        assert captured_this_slot(p, "ts_utc", now) is True, "same ten-minute slot"
        assert captured_this_slot(p, "ts_utc", now.replace(minute=35)) is False, "next slot reopens"
    print("  [ok] slot gate: one capture per ten-minute UTC slot, reopens on the next")

    # 12. raw parquet is written OUTSIDE the box state dir's published stage,
    #     one file per pass, never a rewrite -- and never anywhere under this
    #     checkout (see module docstring, "RAW VS PUBLISHED").
    if duckdb is not None:
        with tf.TemporaryDirectory() as d:
            raw_rows_t = [{"ts_utc": TS_FIXTURE, "ccy": "VND", "side": "buy", "adv_no": "1",
                           "price": 26000.0, "min_amt": 0.0, "max_amt": 1000.0,
                           "surplus_amount": 10.0, "tradable_quantity": 10.0}]
            path1 = write_raw_parquet(raw_rows_t, TS_FIXTURE, state_dir=d)
            assert path1 and os.path.exists(path1)
            assert path1.startswith(os.path.join(d, "raw", "2026-10"))
            assert not path1.startswith(HERE), "raw parquet must never land inside this checkout"
            ts2 = "2026-10-03T00:10:00+00:00"
            path2 = write_raw_parquet(raw_rows_t, ts2, state_dir=d)
            assert path2 != path1 and os.path.exists(path1), \
                "a later pass writes its own file; it never rewrites an earlier one"
            con = duckdb.connect()
            n = con.execute(
                f"SELECT count(*) FROM read_parquet('{os.path.join(d, 'raw', '2026-10')}/*.parquet')"
            ).fetchone()[0]
            con.close()
            assert n == 2, "both passes' rows are readable as one month via a glob"
        print("  [ok] raw parquet: one file per pass under the box state dir, "
              "never inside this checkout, a month reads as one glob")
    else:
        print("  [skip] duckdb not installed -- raw parquet test skipped")

    # 13. published stage CSV: append-only, header matches PUBLISHED_FIELDS,
    #     staged outside this checkout.
    with tf.TemporaryDirectory() as d:
        row = _base_row(TS_FIXTURE, "VND")
        row["source_ok"] = True
        p = write_published_stage([row], state_dir=d)
        assert p == os.path.join(d, "published_depth.csv")
        with open(p, newline="") as f:
            r = next(csv.DictReader(f))
        assert set(r) == set(PUBLISHED_FIELDS)
    print("  [ok] published stage CSV: header matches PUBLISHED_FIELDS exactly")

    # 14. lock: a live pid blocks; a stale (dead) pid is reclaimed rather
    #     than wedging every pass behind a crashed one forever.
    with tf.TemporaryDirectory() as d:
        assert acquire_lock(d) is True
        assert acquire_lock(d) is False, "still held by our own live pid"
        release_lock(d)
        with open(lock_path(d), "w") as f:
            f.write("999999999")  # a pid that cannot exist
        assert acquire_lock(d) is True, "a dead pid's lock is reclaimed, not wedged"
        release_lock(d)
    print("  [ok] lock: a live pass blocks a second one; a crashed pass's stale "
          "lock is reclaimed, not wedged forever\n")

    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki P2P collector -- box layer (10-min)")
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

    if not a.verify:
        ok, pct = disk_ok(BOX_STATE_DIR)
        if not ok:
            print(f"  [error] disk at {pct}% under {BOX_STATE_DIR}, at or past "
                  f"the {DISK_STOP_PCT}% stop -- collection skipped this pass, "
                  f"no request made", file=sys.stderr)
            sys.exit(1)

        if captured_this_slot(published_stage_path(), "ts_utc"):
            print(f"  {utc_slot():%Y-%m-%dT%H:%M}Z already captured -> "
                  f"{published_stage_path()}, nothing to do")
            return

        if not acquire_lock():
            print(f"  [error] a previous pass still holds {lock_path()} -- "
                  f"skipping rather than overlapping it", file=sys.stderr)
            sys.exit(1)

    try:
        summary, raw, n_ok = collect()

        if not a.verify:
            write_published_stage(summary)
            raw_path = write_raw_parquet(raw, summary[0]["ts_utc"]) if summary else None

        if a.json:
            print(json.dumps(summary, indent=2, default=str))
        else:
            print_table(summary)

        if a.verify:
            return

        print(f"  staged -> {published_stage_path()}")
        print(f"  raw    -> {raw_path or '(no ads this pass)'}\n")
        if run_exit_code(n_ok) != 0:
            print("  [error] TOTAL BLACKOUT -- no currency answered this pass", file=sys.stderr)
            sys.exit(1)
    finally:
        if not a.verify:
            release_lock()


if __name__ == "__main__":
    main()
