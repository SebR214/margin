#!/usr/bin/env python3
"""
One-time backfill of daily USDT *basis* history -> data/basis_history.csv.

This is NOT part of the hourly collector. Run it by hand to seed the map with
history so it shows years on day one:

    python3 tools/backfill_basis.py             # write data/basis_history.csv
    python3 tools/backfill_basis.py --dry-run   # fetch + summarise, write nothing
    python3 tools/backfill_basis.py --selftest  # offline, mocked

Method: each venue's own daily candle API gives a daily USDT close in local
currency; that is crossed against a daily USD FX mid to get basis in bps, using
the SAME sign convention as the live basis layer (see METHODOLOGY):

    basis_bps = (usdt_close_local / fx_mid_local_per_usd - 1) * 10_000

Schema (one row per venue per day):
    date, venue, ccy, usdt_close, fx_mid, basis_bps, source

Two independent history sources, two independent limits:
  - Candle depth is per venue (Bitso's public OHLC is the shallowest).
  - FX depth is fawazahmed0's currency-api (dated, keyless), which starts
    2024-03. Coverage is the SHORTER of the two, so history effectively begins
    when FX history does even where a venue's candles go back further. This is
    stated in METHODOLOGY ('Historical basis').

er-api (the LIVE collector's FX) has no history, hence a different FX source
here; the ~tens-of-bps level difference between the two feeds is recorded in
METHODOLOGY so the history/live seam is understood, not silently smoothed.
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

HTTP_TIMEOUT = 30
UA = {"User-Agent": "margin.wiki backfill/1.0 (+https://margin.wiki)"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "basis_history.csv")
FIELDS = ["date", "venue", "ccy", "usdt_close", "fx_mid", "basis_bps", "source"]

# fawazahmed0 currency-api history begins here; earlier candle rows are dropped
# (no FX to cross against) and counted in the summary.
FX_START = "2024-03-02"


# ------------------------------------------------------------------ I/O
def get_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def _d(ms_or_s, ms=False):
    """Epoch (s or ms) -> 'YYYY-MM-DD' in UTC."""
    ts = ms_or_s / 1000 if ms else ms_or_s
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------- candle fetchers
# Each returns [(date 'YYYY-MM-DD', usdt_close float)], newest-or-oldest order
# irrelevant (assembled by date later). Raises on hard failure; the caller
# isolates a single venue so one dead API does not sink the backfill.
def candles_btcturk(ccy, fetch=get_json):
    # api.btcturk.com v2/ohlc (the graph.* host is unreachable). `last=N` daily.
    d = fetch("https://api.btcturk.com/api/v2/ohlc?pairSymbol=USDTTRY&last=2500")
    return [(_d(c["time"], ms=True), float(c["close"]))
            for c in d.get("data", []) if c.get("close")]


def candles_upbit(ccy, fetch=get_json):
    # v1/candles/days, 200 per page, paginate backwards via `to` (exclusive).
    base = "https://api.upbit.com/v1/candles/days?market=KRW-USDT&count=200"
    out, to, seen = [], None, None
    for _ in range(60):  # 60*200 = 12k days ceiling; real history is far less
        url = base + (f"&to={to}" if to else "")
        page = fetch(url)
        if not page:
            break
        for c in page:
            out.append((c["candle_date_time_utc"][:10], float(c["trade_price"])))
        oldest = page[-1]["candle_date_time_utc"]
        if oldest == seen:            # no progress -> stop (guard vs loop)
            break
        seen, to = oldest, oldest.replace("T", " ")
        if len(page) < 200:
            break
        time.sleep(0.15)              # be polite to Upbit
    return out


def candles_indodax(ccy, fetch=get_json):
    # tradingview/history_v2, note tf=1D (NOT resolution=). [{Time,Close}].
    frm, to = 1_500_000_000, int(time.time())  # 2017-07 -> now
    d = fetch(f"https://indodax.com/tradingview/history_v2?symbol=USDTIDR"
              f"&tf=1D&from={frm}&to={to}")
    return [(_d(c["Time"]), float(c["Close"])) for c in d if c.get("Close")]


def candles_bitkub(ccy, fetch=get_json):
    # tradingview/history, symbol USDT_THB. {s, t[], c[]}.
    frm, to = 1_500_000_000, int(time.time())
    d = fetch(f"https://api.bitkub.com/tradingview/history?symbol=USDT_THB"
              f"&resolution=1D&from={frm}&to={to}")
    if d.get("s") != "ok":
        raise ValueError(f"bitkub status {d.get('s')}")
    return [(_d(t), float(c)) for t, c in zip(d["t"], d["c"])]


def candles_bitso(ccy, fetch=get_json):
    # v3/ohlc daily buckets. close = last_rate. Public window is shallow.
    d = fetch("https://api.bitso.com/api/v3/ohlc?book=usdt_mxn&time_bucket=86400")
    return [(_d(c["bucket_start_time"], ms=True), float(c["last_rate"]))
            for c in d.get("payload", []) if c.get("last_rate")]


VENUES = [
    {"name": "BTCTurk", "ccy": "TRY", "candles_fn": candles_btcturk,
     "source": "btcturk/v2-ohlc+fawazahmed0"},
    {"name": "Upbit", "ccy": "KRW", "candles_fn": candles_upbit,
     "source": "upbit/candles-days+fawazahmed0"},
    {"name": "Indodax", "ccy": "IDR", "candles_fn": candles_indodax,
     "source": "indodax/history_v2+fawazahmed0"},
    {"name": "Bitkub", "ccy": "THB", "candles_fn": candles_bitkub,
     "source": "bitkub/tv-history+fawazahmed0"},
    {"name": "Bitso", "ccy": "MXN", "candles_fn": candles_bitso,
     "source": "bitso/v3-ohlc+fawazahmed0"},
]


# --------------------------------------------------------------- FX history
def fx_day(date_iso, fetch=get_json):
    """{ccy_lower: rate} for one day, or None. jsDelivr then a pages.dev mirror."""
    for url in (
        f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date_iso}"
        f"/v1/currencies/usd.json",
        f"https://{date_iso}.currency-api.pages.dev/v1/currencies/usd.json",
    ):
        try:
            usd = (fetch(url) or {}).get("usd") or {}
            if usd:
                return usd
        except Exception:
            continue
    return None


# ------------------------------------------------------------- backfill core
def assemble(venue_candles, fx_by_date):
    """
    Pure join: {venue_name: [(date, close)]} + {date: {ccy: fx}} -> (rows, stats).
    Drops rows before FX coverage or with no FX for the ccy; counts the drops.
    """
    rows, dropped_fx = [], 0
    ccy_of = {v["name"]: v["ccy"] for v in VENUES}
    src_of = {v["name"]: v["source"] for v in VENUES}
    for name, candles in venue_candles.items():
        ccy = ccy_of[name]
        for date, close in candles:
            if date < FX_START:
                dropped_fx += 1
                continue
            usd = fx_by_date.get(date)
            fx = usd.get(ccy.lower()) if usd else None
            if not fx:
                dropped_fx += 1
                continue
            rows.append({
                "date": date, "venue": name, "ccy": ccy,
                "usdt_close": round(close, 8), "fx_mid": round(fx, 6),
                "basis_bps": round((close / fx - 1) * 1e4, 2),
                "source": src_of[name],
            })
    rows.sort(key=lambda r: (r["date"], r["venue"]))
    return rows, dropped_fx


def run_backfill(dry_run=False):
    # 1. candles per venue, isolated so one dead API doesn't sink the rest
    venue_candles = {}
    for v in VENUES:
        try:
            cs = v["candles_fn"](v["ccy"])
            cs = [(d, c) for d, c in cs if c > 0]
            venue_candles[v["name"]] = cs
            span = f"{min(d for d, _ in cs)}..{max(d for d, _ in cs)}" if cs else "EMPTY"
            print(f"  [candles] {v['name']:<10} {len(cs):>5} days  {span}")
        except Exception as e:
            venue_candles[v["name"]] = []
            print(f"  [candles] {v['name']:<10} FAILED: {type(e).__name__}: {e}",
                  file=sys.stderr)

    # 2. one FX fetch per unique date we actually need (>= FX_START)
    dates = sorted({d for cs in venue_candles.values() for d, _ in cs if d >= FX_START})
    print(f"  [fx] fetching {len(dates)} daily FX snapshots "
          f"({dates[0] if dates else '-'}..{dates[-1] if dates else '-'})")
    fx_by_date, miss = {}, 0
    for i, date in enumerate(dates):
        fx_by_date[date] = fx_day(date)
        if fx_by_date[date] is None:
            miss += 1
        if (i + 1) % 100 == 0:
            print(f"        {i + 1}/{len(dates)} fx days")
    if miss:
        print(f"  [fx] {miss} dates had no FX (dropped)", file=sys.stderr)

    # 3. join
    rows, dropped = assemble(venue_candles, fx_by_date)
    print(f"\n  assembled {len(rows)} rows  ({dropped} dropped: pre-{FX_START} or no FX)")
    per_venue = {}
    for r in rows:
        per_venue.setdefault(r["venue"], []).append(r)
    for name, rs in sorted(per_venue.items()):
        b = [r["basis_bps"] for r in rs]
        print(f"    {name:<10} {len(rs):>5} rows  {rs[0]['date']}..{rs[-1]['date']}"
              f"   basis {min(b):+.0f}..{max(b):+.0f} bps")

    if dry_run:
        print("\n  --dry-run: nothing written\n")
        return rows

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  wrote {len(rows)} rows -> {OUT}\n")
    return rows


# -------------------------------------------------------------- selftest
def selftest():
    # date helpers
    assert _d(1723269600000, ms=True) == "2024-08-10", _d(1723269600000, ms=True)
    assert _d(1785456000) == "2026-07-31", _d(1785456000)

    # candle parsers against captured payload shapes
    bt = candles_btcturk("TRY", fetch=lambda u: {"data": [
        {"time": 1786320000000, "close": "47.611"},
        {"time": 1786233600000, "close": "47.607"}]})
    assert bt == [("2026-08-10", 47.611), ("2026-08-09", 47.607)], bt

    up = candles_upbit("KRW", fetch=lambda u: [
        {"candle_date_time_utc": "2026-08-10T00:00:00", "trade_price": 1410.0},
        {"candle_date_time_utc": "2026-08-09T00:00:00", "trade_price": 1408.0}]
        if "to=" not in u else [])
    assert up[0] == ("2026-08-10", 1410.0) and len(up) == 2, up

    ind = candles_indodax("IDR", fetch=lambda u: [
        {"Time": 1785456000, "Close": 17959}, {"Time": 1785542400, "Close": 17900}])
    assert ind == [("2026-07-31", 17959.0), ("2026-08-01", 17900.0)], ind

    bk = candles_bitkub("THB", fetch=lambda u: {"s": "ok",
        "t": [1785456000, 1785542400], "c": [33.0, 33.1]})
    assert bk == [("2026-07-31", 33.0), ("2026-08-01", 33.1)], bk

    bs = candles_bitso("MXN", fetch=lambda u: {"payload": [
        {"bucket_start_time": 1723269600000, "last_rate": "18.802"}]})
    assert bs == [("2024-08-10", 18.802)], bs
    print("  [ok] all 5 candle parsers map their real payload shape to (date, close)")

    # a venue whose candle API dies is isolated, not fatal (assemble still runs)
    vc = {"BTCTurk": [("2025-01-01", 34.0)], "Upbit": [],
          "Indodax": [("2025-01-01", 16000.0)], "Bitkub": [], "Bitso": []}
    fx = {"2025-01-01": {"try": 35.36, "idr": 16300.0}}
    rows, dropped = assemble(vc, fx)
    assert len(rows) == 2 and dropped == 0, (rows, dropped)
    tr = next(r for r in rows if r["venue"] == "BTCTurk")
    # 34.0 / 35.36 - 1 = -3.85% ... = -384.6 bps (USDT cheap to the USD mid)
    assert abs(tr["basis_bps"] - (-384.62)) < 0.5, tr
    print("  [ok] assemble joins candles x FX with the live basis sign convention")

    # rows before FX coverage or with no FX for the ccy are dropped + counted
    vc2 = {"BTCTurk": [("2020-01-01", 5.9), ("2025-06-01", 40.0)],
           "Upbit": [], "Indodax": [], "Bitkub": [], "Bitso": []}
    fx2 = {"2025-06-01": {"try": 40.0}}   # note: no 'try' pre-FX_START date
    rows2, dropped2 = assemble(vc2, fx2)
    assert len(rows2) == 1 and dropped2 == 1, (rows2, dropped2)
    assert rows2[0]["date"] == "2025-06-01"
    print("  [ok] pre-coverage / missing-FX rows dropped and counted, never guessed")

    # fx_day falls back to the mirror host, then to None
    seq = iter([Exception, {"usd": {"idr": 17817.0}}])

    def fx_fetch(url):
        v = next(seq)
        if isinstance(v, type) and issubclass(v, Exception):
            raise v("jsdelivr down")
        return v
    assert fx_day("2026-08-10", fetch=fx_fetch) == {"idr": 17817.0}
    assert fx_day("1900-01-01", fetch=lambda u: (_ for _ in ()).throw(RuntimeError())) is None
    print("  [ok] fx_day tries mirror on failure, returns None when both fail")

    assert set(FIELDS) == {"date", "venue", "ccy", "usdt_close", "fx_mid",
                           "basis_bps", "source"}
    print("  [ok] schema matches the agreed columns\n")
    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="one-time USDT basis backfill")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")
    run_backfill(dry_run=a.dry_run)


if __name__ == "__main__":
    main()
