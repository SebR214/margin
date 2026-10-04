#!/usr/bin/env python3
"""
The history layer: "reported, not observed" -> data/history/*.csv

Backfilled history lives HERE and nowhere else. It never feeds the index, a
published price, the observed series (data/basis.csv, samples.csv, ...) or the
unbroken-hours count; tools/check_history_isolation.py proves that. Every row
carries the label below and the endpoint it came from.

Rows come ONLY from an exchange's or data provider's own history endpoint.
Nothing is derived, filled, interpolated or crossed against another series:
a candle is a candle the venue reported, a rate is a rate the provider
published. A gap in the endpoint stays a gap in the file. Candles still open
(period end in the future) are skipped, so a stored row never changes.

    python3 tools/backfill_history.py                 # all venues, write files
    python3 tools/backfill_history.py --dry-run       # fetch + summarise only
    python3 tools/backfill_history.py --only Upbit,FX # subset
    python3 tools/backfill_history.py --hourly-since 2024-01-01
    python3 tools/backfill_history.py --selftest      # offline, mocked

Idempotent: files are merged by timestamp, so a second run adds nothing; an
existing row is never overwritten (a changed upstream value is only counted
and reported as a conflict). Incremental: a re-run refetches only from two days
before the newest stored row.

Files (new series, new files; data/basis_history.csv is untouched):
    data/history/candles_<venue>_<1h|1d>.csv
        ts_utc,venue,ccy,pair,interval,close,label,source
    data/history/official_fx_daily.csv
        date,ccy,per_usd,label,source
    data/history/parallel_dollar_daily.csv
        date,market,ccy,buy,sell,label,source
    data/history/manifest.json   coverage summary, written last

Hourly depth is capped by --hourly-since (default 2025-01-01) to keep the repo
small; daily candles are taken at each venue's full offered depth.
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

LABEL = "reported, not observed"
HTTP_TIMEOUT = 30
UA = {"User-Agent": "margin.wiki history/1.0 (+https://margin.wiki)"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "history")
CANDLE_FIELDS = ["ts_utc", "venue", "ccy", "pair", "interval", "close", "label", "source"]
FX_FIELDS = ["date", "ccy", "per_usd", "label", "source"]
PAR_FIELDS = ["date", "market", "ccy", "buy", "sell", "label", "source"]
DEFAULT_HOURLY_SINCE = "2025-01-01"
STEP = {"1h": 3600, "1d": 86400}


# ------------------------------------------------------------------ I/O
def get_json(url):
    for wait in (2, 6, 15, None):      # a venue saying "slow down" gets a pause, not a hammer
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
        if r.status_code != 429 or wait is None:
            break
        time.sleep(wait)
    r.raise_for_status()
    return r.json()


def iso(ts):
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(date_iso):
    return int(dt.datetime.strptime(date_iso, "%Y-%m-%d")
               .replace(tzinfo=dt.timezone.utc).timestamp())


def _num(x):
    return float(x)


# --------------------------------------------------------- candle fetchers
# Each fetcher(interval, start, fetch, now) -> [(open_ts_seconds, close)] for
# candles opened at or after `start` (epoch seconds). Order irrelevant.
def f_upbit(interval, start, fetch=get_json, now=None):
    kind = "minutes/60" if interval == "1h" else "days"
    base = f"https://api.upbit.com/v1/candles/{kind}?market=KRW-USDT&count=200"
    out, to = [], None
    for _ in range(500):
        page = fetch(base + (f"&to={to}" if to else ""))
        if not page:
            break
        for c in page:
            t = epoch_dt(c["candle_date_time_utc"])
            out.append((t, _num(c["trade_price"])))
        oldest = page[-1]["candle_date_time_utc"]
        if epoch_dt(oldest) <= start or len(page) < 200:
            break
        to = oldest.replace("T", " ")
        time.sleep(0.12)
    return out


def epoch_dt(s):
    """'YYYY-MM-DDTHH:MM:SS' (UTC) -> epoch seconds."""
    return int(dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
               .replace(tzinfo=dt.timezone.utc).timestamp())


def f_bithumb(interval, start, fetch=get_json, now=None):
    kind = "minutes/60" if interval == "1h" else "days"
    base = f"https://api.bithumb.com/v1/candles/{kind}?market=KRW-USDT&count=200"
    out, to, seen = [], None, None
    for _ in range(500):
        page = fetch(base + (f"&to={to}" if to else ""))
        if not isinstance(page, list) or not page:
            break
        for c in page:
            out.append((epoch_dt(c["candle_date_time_utc"]), _num(c["trade_price"])))
        oldest = page[-1]["candle_date_time_utc"]
        if oldest == seen or epoch_dt(oldest) <= start or len(page) < 200:
            break
        # Bithumb reads `to` as KST, so page on the KST stamp (UTC would skip 9h)
        seen, to = oldest, page[-1]["candle_date_time_kst"].replace("T", " ")
        time.sleep(0.12)
    return out


def f_coinone(interval, start, fetch=get_json, now=None):
    base = f"https://api.coinone.co.kr/public/v2/chart/KRW/USDT?interval={interval}&size=500"
    out, ts = [], None
    for _ in range(200):
        d = fetch(base + (f"&timestamp={ts}" if ts else ""))
        chart = d.get("chart") or []
        if d.get("result") != "success" or not chart:
            break
        for c in chart:
            out.append((int(c["timestamp"]) // 1000, _num(c["close"])))
        oldest = min(int(c["timestamp"]) for c in chart)
        if d.get("is_last") or oldest // 1000 <= start:
            break
        ts = oldest
        time.sleep(0.12)
    return out


def f_btcturk(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    out = []
    if interval == "1d":
        d = fetch("https://api.btcturk.com/api/v2/ohlc?pairSymbol=USDTTRY&last=5000")
        return [(int(c["time"]) // 1000, _num(c["close"]))
                for c in d.get("data", []) if c.get("close")]
    t = start
    while t < now:
        e = min(t + 30 * 86400, now)
        d = fetch("https://graph-api.btcturk.com/v1/klines/history?symbol=USDTTRY"
                  f"&resolution=60&from={t}&to={e}")
        if d.get("s") == "ok":
            out += [(int(a), _num(b)) for a, b in zip(d["t"], d["c"])]
        t = e
        time.sleep(0.12)
    return out


def f_indodax(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    # the endpoint returns at most ~731 candles per call (the NEWEST ones in the
    # window), so both intervals page forward in windows that fit under the cap
    span = 700 * 86400 if interval == "1d" else 7 * 86400
    tf = "1D" if interval == "1d" else "60"
    out, t = [], start
    while t < now:
        e = min(t + span, now)
        d = fetch(f"https://indodax.com/tradingview/history_v2?symbol=USDTIDR&tf={tf}"
                  f"&from={t}&to={e}")
        out += [(int(c["Time"]), _num(c["Close"])) for c in d if c.get("Close")]
        t = e
        time.sleep(0.12)
    return out


def f_bitkub(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    res = "60" if interval == "1h" else "1D"
    d = fetch(f"https://api.bitkub.com/tradingview/history?symbol=USDT_THB"
              f"&resolution={res}&from={start}&to={now}")
    if d.get("s") != "ok":
        raise ValueError(f"bitkub status {d.get('s')}")
    return [(int(t), _num(c)) for t, c in zip(d["t"], d["c"])]


def f_bitso(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    b = 3600 if interval == "1h" else 86400
    span = (365 if interval == "1d" else 30) * 86400   # `start`/`end` are epoch ms
    out, t = [], start
    while t < now:
        e = min(t + span, now)
        d = fetch(f"https://api.bitso.com/api/v3/ohlc?book=usdt_mxn&time_bucket={b}"
                  f"&start={t * 1000}&end={e * 1000}")
        out += [(int(c["bucket_start_time"]) // 1000, _num(c["last_rate"]))
                for c in d.get("payload", []) if c.get("last_rate")]
        t = e
        time.sleep(0.3)
    return out


def f_foxbit(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    step = STEP[interval]
    out, t = [], start
    while t < now:
        s = iso(t)
        d = fetch("https://api.foxbit.com.br/rest/v3/markets/usdtbrl/candlesticks"
                  f"?interval={interval}&limit=500&start_time={s}")
        if not isinstance(d, list) or not d:
            if t + 500 * step >= now:
                break
            t += 500 * step            # before the pair's first candle: step on
            continue
        for c in d:
            out.append((int(c[0]) // 1000, _num(c[4])))
        last = max(int(c[0]) // 1000 for c in d)
        if last + step <= t:
            break
        t = last + step
        time.sleep(0.12)
    return out


def f_bitopro(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    res = "1h" if interval == "1h" else "1d"
    out, t = [], start
    span = 30 * 86400 if interval == "1h" else 600 * 86400
    while t < now:
        e = min(t + span, now)
        d = fetch(f"https://api.bitopro.com/v3/trading-history/usdt_twd?resolution={res}"
                  f"&from={t}&to={e}")
        out += [(int(c["timestamp"]) // 1000, _num(c["close"])) for c in d.get("data", [])]
        t = e
        time.sleep(0.12)
    return out


def f_max(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    period = 60 if interval == "1h" else 1440
    out, t = [], start
    for _ in range(100):
        d = fetch(f"https://max-api.maicoin.com/api/v2/k?market=usdttwd&limit=10000"
                  f"&period={period}&timestamp={t}")
        if not d:
            break
        out += [(int(c[0]), _num(c[4])) for c in d]
        last = max(int(c[0]) for c in d)
        if last + period * 60 >= now or len(d) < 10000:
            break
        t = last + period * 60
        time.sleep(0.12)
    return out


def f_coinsph(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    step = STEP[interval]
    out, t = [], start
    for _ in range(300):
        e = t + 1000 * step
        d = fetch("https://api.pro.coins.ph/openapi/quote/v1/klines?symbol=USDTPHP"
                  f"&interval={interval}&limit=1000&startTime={t * 1000}&endTime={e * 1000}")
        if not isinstance(d, list) or not d:
            if e >= now:
                break
            t = e                      # before the pair's first candle: step on
            continue
        out += [(int(c[0]) // 1000, _num(c[4])) for c in d]
        last = max(int(c[0]) // 1000 for c in d)
        if last + step <= t:
            break
        if e >= now and len(d) < 1000:
            break
        t = max(last + step, e) if len(d) < 1000 else last + step
        time.sleep(0.12)
    return out


def f_btcmarkets(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    step = STEP[interval]
    win = "1h" if interval == "1h" else "1d"
    out, t = [], start
    for _ in range(100):
        d = fetch("https://api.btcmarkets.net/v3/markets/USDT-AUD/candles"
                  f"?timeWindow={win}&from={iso(t)}&to={iso(now)}&limit=1000")
        if not isinstance(d, list) or not d:
            break
        out += [(epoch_dt(c[0]), _num(c[4])) for c in d if _num(c[5]) > 0]  # no trade = no candle
        last = max(epoch_dt(c[0]) for c in d)
        if last + step >= now or last + step <= t:
            break
        t = last + step
        time.sleep(0.2)
    return out


def f_wazirx(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    step = STEP[interval]
    span = 1900 * step                  # the endpoint caps a call at 2000 candles
    iv = "1h" if interval == "1h" else "1d"
    out, t = [], start
    while t < now:
        e = min(t + span, now)
        d = fetch(f"https://api.wazirx.com/sapi/v1/klines?symbol=usdtinr&interval={iv}"
                  f"&limit=2000&startTime={t}&endTime={e}")
        if isinstance(d, list):
            out += [(int(c[0]), _num(c[4])) for c in d if _num(c[5]) > 0]  # no trade = no candle
        t = e
        time.sleep(0.6)
    return out


def f_coindcx(interval, start, fetch=get_json, now=None):
    now = now or int(time.time())
    step = STEP[interval]
    span = 900 * step                   # the endpoint caps a call at 1000 candles
    iv = "1h" if interval == "1h" else "1d"
    out, t = [], start
    while t < now:
        e = min(t + span, now)
        d = fetch("https://public.coindcx.com/market_data/candles?pair=I-USDT_INR"
                  f"&interval={iv}&limit=1000&startTime={t * 1000}&endTime={e * 1000}")
        if isinstance(d, list):
            out += [(int(c["time"]) // 1000, _num(c["close"])) for c in d
                    if _num(c.get("volume") or 0) > 0]  # no trade = no candle
        t = e
        time.sleep(0.4)
    return out


# name, ccy, pair, fetcher, source host/path (named on every row)
VENUES = [
    ("Upbit", "KRW", "KRW-USDT", f_upbit, "api.upbit.com/v1/candles"),
    ("Bithumb", "KRW", "KRW-USDT", f_bithumb, "api.bithumb.com/v1/candles"),
    ("Coinone", "KRW", "KRW/USDT", f_coinone, "api.coinone.co.kr/public/v2/chart"),
    ("BTCTurk", "TRY", "USDTTRY", f_btcturk, "graph-api.btcturk.com/v1/klines/history;api.btcturk.com/api/v2/ohlc"),
    ("Indodax", "IDR", "USDTIDR", f_indodax, "indodax.com/tradingview/history_v2"),
    ("Bitkub", "THB", "USDT_THB", f_bitkub, "api.bitkub.com/tradingview/history"),
    ("Bitso", "MXN", "usdt_mxn", f_bitso, "api.bitso.com/api/v3/ohlc"),
    ("Foxbit", "BRL", "usdtbrl", f_foxbit, "api.foxbit.com.br/rest/v3/markets/usdtbrl/candlesticks"),
    ("BitoPro", "TWD", "usdt_twd", f_bitopro, "api.bitopro.com/v3/trading-history"),
    ("MAX", "TWD", "usdttwd", f_max, "max-api.maicoin.com/api/v2/k"),
    ("Coins.ph", "PHP", "USDTPHP", f_coinsph, "api.pro.coins.ph/openapi/quote/v1/klines"),
    ("BTC Markets", "AUD", "USDT-AUD", f_btcmarkets, "api.btcmarkets.net/v3/markets/USDT-AUD/candles"),
    ("WazirX", "INR", "usdtinr", f_wazirx, "api.wazirx.com/sapi/v1/klines"),
    ("CoinDCX", "INR", "I-USDT_INR", f_coindcx, "public.coindcx.com/market_data/candles"),
]
# Probed and not collected: Paribu (login wall), Mercado Bitcoin (bot challenge),
# Independent Reserve (no candle/history endpoint), Luno (candles need an API
# key, HTTP 401), Pintu (price-changes only, no candles), Coinbase (login-gated,
# never scraped). See METHODOLOGY.


# ----------------------------------------------------------- file merging
def fname(venue, interval):
    return os.path.join(OUT_DIR, f"candles_{venue.lower().replace('.', '').replace(' ', '')}_{interval}.csv")


def read_rows(path, key):
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as f:
        return {key(r): r for r in csv.DictReader(f)}


def write_rows(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def candle_rows(venue, ccy, pair, interval, source, candles, now):
    """Pure: raw (ts, close) -> rows. Drops open candles and non-positive closes;
    de-duplicates by ts. Nothing is created that the venue did not report."""
    step = STEP[interval]
    seen, rows = {}, []
    for ts, close in candles:
        if close <= 0 or ts + step > now:
            continue
        seen[ts] = close
    for ts in sorted(seen):
        rows.append({"ts_utc": iso(ts), "venue": venue, "ccy": ccy, "pair": pair,
                     "interval": interval, "close": repr(seen[ts]),
                     "label": LABEL, "source": source})
    return rows


def merge(existing, new, key):
    """existing {key: row}, new [row] -> (merged sorted list, added, conflicts)."""
    added = conflicts = 0
    for r in new:
        k = key(r)
        if k not in existing:
            existing[k] = r
            added += 1
        elif existing[k].get("close", existing[k].get("per_usd")) != \
                r.get("close", r.get("per_usd")):
            conflicts += 1          # never overwrite a stored row
    return [existing[k] for k in sorted(existing)], added, conflicts


def run_candles(only, hourly_since, dry, now):
    summary = {}
    for venue, ccy, pair, fn, src in VENUES:
        if only and venue not in only:
            continue
        for interval in ("1h", "1d"):
            path = fname(venue, interval)
            ex = read_rows(path, lambda r: r["ts_utc"])
            floor = epoch(hourly_since) if interval == "1h" else 1_500_000_000
            if ex:
                floor = max(floor, epoch_dt(max(ex)) - 2 * 86400)
            tag = f"{venue:<9}{interval}"
            try:
                raw = fn(interval, floor, get_json, now)
                rows = candle_rows(venue, ccy, pair, interval, f"{src}", raw, now)
                rows = [r for r in rows if epoch_dt(r["ts_utc"]) >= floor]
                merged, added, conf = merge(ex, rows, lambda r: r["ts_utc"])
            except Exception as e:
                print(f"  [candles] {tag} FAILED: {type(e).__name__}: {str(e)[:100]}",
                      file=sys.stderr)
                summary[f"{venue}_{interval}"] = {"error": f"{type(e).__name__}"}
                continue
            if not merged:
                print(f"  [candles] {tag} EMPTY")
                continue
            print(f"  [candles] {tag} {len(merged):>6} rows (+{added}, {conf} conflicts)  "
                  f"{merged[0]['ts_utc'][:10]}..{merged[-1]['ts_utc'][:10]}")
            summary[f"{venue}_{interval}"] = {
                "file": os.path.relpath(path, ROOT), "rows": len(merged),
                "first": merged[0]["ts_utc"], "last": merged[-1]["ts_utc"],
                "ccy": ccy, "source": src}
            if not dry and added:
                write_rows(path, CANDLE_FIELDS, merged)
    return summary


# ------------------------------------------------- official FX (Frankfurter)
FX_SYMBOLS = "KRW,TRY,IDR,THB,MXN,BRL,PHP,SGD,AUD,NZD,INR"
FX_SOURCE = "api.frankfurter.dev (ECB reference rates, per 1 USD)"


def fx_rows(payload):
    """Frankfurter {rates:{date:{CCY:x}}} -> rows, exactly as published."""
    rows = []
    for date, m in payload.get("rates", {}).items():
        for ccy, v in m.items():
            rows.append({"date": date, "ccy": ccy, "per_usd": repr(float(v)),
                         "label": LABEL, "source": FX_SOURCE})
    rows.sort(key=lambda r: (r["date"], r["ccy"]))
    return rows


# Taiwan: the ECB publishes no TWD. The same Frankfurter host serves the Central
# Bank of the Republic of China (Taiwan)'s own interbank spot closing rate
# (v2 `providers=CBC`, quoted per 1 USD): one named central bank's published
# series, not Frankfurter's blended rate, so nothing is averaged or crossed.
CBC_SOURCE = ("api.frankfurter.dev/v2 providers=CBC (Central Bank of the Republic "
              "of China (Taiwan), interbank spot closing, per 1 USD)")


def cbc_rows(payload):
    """Frankfurter v2 [{date, base:USD, quote:TWD, rate}] -> rows, as published."""
    rows = []
    for c in payload:
        if c.get("base") != "USD" or c.get("quote") != "TWD" or not c.get("rate"):
            continue
        rows.append({"date": c["date"], "ccy": "TWD", "per_usd": repr(float(c["rate"])),
                     "label": LABEL, "source": CBC_SOURCE})
    rows.sort(key=lambda r: r["date"])
    return rows


def run_fx(dry, now):
    path = os.path.join(OUT_DIR, "official_fx_daily.csv")
    ex = read_rows(path, lambda r: (r["date"], r["ccy"]))
    start = "2018-01-01"
    if ex:
        start = max(k[0] for k in ex)
    end = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%d")
    d = get_json(f"https://api.frankfurter.dev/v1/{start}..{end}?base=USD&symbols={FX_SYMBOLS}")
    rows = fx_rows(d)
    twd_dates = [k[0] for k in ex if k[1] == "TWD"]
    twd_start = max(twd_dates) if twd_dates else "2018-01-01"
    rows += cbc_rows(get_json("https://api.frankfurter.dev/v2/rates?base=USD&quotes=TWD"
                              f"&providers=CBC&from={twd_start}&to={end}"))
    merged, added, conf = merge(ex, rows, lambda r: (r["date"], r["ccy"]))
    print(f"  [fx] official_fx_daily {len(merged):>6} rows (+{added}, {conf} conflicts)  "
          f"{merged[0]['date']}..{merged[-1]['date']}")
    if not dry and added:
        write_rows(path, FX_FIELDS, merged)
    return {"official_fx_daily": {"file": os.path.relpath(path, ROOT), "rows": len(merged),
            "first": merged[0]["date"], "last": merged[-1]["date"],
            "ccys": FX_SYMBOLS, "source": FX_SOURCE,
            "gap": "no ECB series for ARS, NGN, VES, EGP, DZD; TWD is the Taiwan central bank's own series (CBC)"}}


# ------------------------------------------ parallel dollar (Argentina blue)
PAR_URL = "https://api.argentinadatos.com/v1/cotizaciones/dolares/blue"
PAR_SOURCE = "api.argentinadatos.com/v1/cotizaciones/dolares/blue (MIT)"


def par_rows(payload):
    rows = []
    for c in payload:
        if c.get("casa") != "blue" or not c.get("fecha"):
            continue
        rows.append({"date": c["fecha"], "market": "blue", "ccy": "ARS",
                     "buy": repr(float(c["compra"])), "sell": repr(float(c["venta"])),
                     "label": LABEL, "source": PAR_SOURCE})
    rows.sort(key=lambda r: r["date"])
    return rows


def run_parallel(dry):
    path = os.path.join(OUT_DIR, "parallel_dollar_daily.csv")
    ex = read_rows(path, lambda r: (r["date"], r["market"]))
    rows = par_rows(get_json(PAR_URL))
    merged, added, conf = merge(ex, rows, lambda r: (r["date"], r["market"]))
    print(f"  [parallel] argentina blue {len(merged):>6} rows (+{added})  "
          f"{merged[0]['date']}..{merged[-1]['date']}")
    if not dry and added:
        write_rows(path, PAR_FIELDS, merged)
    return {"parallel_dollar_daily": {"file": os.path.relpath(path, ROOT),
            "rows": len(merged), "first": merged[0]["date"], "last": merged[-1]["date"],
            "source": PAR_SOURCE}}


# ------------------------------------------------------------------- main
def run(only=None, hourly_since=DEFAULT_HOURLY_SINCE, dry=False):
    now = int(time.time())
    only = set(only) if only else None
    summary = {}
    summary.update(run_candles(only, hourly_since, dry, now))
    if not only or "FX" in only:
        try:
            summary.update(run_fx(dry, now))
        except Exception as e:
            print(f"  [fx] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    if not only or "Parallel" in only:
        try:
            summary.update(run_parallel(dry))
        except Exception as e:
            print(f"  [parallel] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    if dry:
        print("\n  --dry-run: nothing written\n")
        return summary
    if not only:   # a subset run must not shrink the manifest
        man = {"label": LABEL, "files": summary}
        with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
            json.dump(man, f, indent=1, sort_keys=True)
            f.write("\n")
    return summary


def selftest():
    now = 1_790_000_000
    # open candle and bad close are dropped; duplicates collapse; nothing invented
    rows = candle_rows("V", "XXX", "P", "1h", "s",
                       [(now - 7200, 1.5), (now - 7200, 1.5), (now - 1800, 1.6), (now - 10000, 0)], now)
    assert [r["close"] for r in rows] == ["1.5"], rows
    assert rows[0]["label"] == LABEL and rows[0]["source"] == "s"
    # merge is idempotent and never overwrites
    ex, added, conf = merge({}, rows, lambda r: r["ts_utc"])
    assert added == 1
    again, added2, _ = merge({r["ts_utc"]: r for r in ex}, rows, lambda r: r["ts_utc"])
    assert added2 == 0 and again == ex
    changed = [dict(rows[0], close="9.9")]
    kept, a3, c3 = merge({r["ts_utc"]: r for r in ex}, changed, lambda r: r["ts_utc"])
    assert a3 == 0 and c3 == 1 and kept[0]["close"] == "1.5"
    # parsers
    up = f_upbit("1h", 0, fetch=lambda u: [
        {"candle_date_time_utc": "2026-10-03T01:00:00", "trade_price": 1359.0},
        {"candle_date_time_utc": "2026-10-03T00:00:00", "trade_price": 1358.0}], now=now)
    assert up == [(1790989200, 1359.0), (1790985600, 1358.0)], up
    bk = f_bitkub("1h", 0, fetch=lambda u: {"s": "ok", "t": [1790985600], "c": [33.0]}, now=now)
    assert bk == [(1790985600, 33.0)]
    mx = f_max("1h", 0, fetch=lambda u: [[1790985600, 1, 2, 0, 31.9, 5]], now=now)
    assert mx == [(1790985600, 31.9)]
    pages = iter([[[1790985600000, "1", "2", "0", "62.5", "9"]]])
    cp = f_coinsph("1h", 1790985000, fetch=lambda u: next(pages, []), now=now)
    assert cp == [(1790985600, 62.5)]
    fx = fx_rows({"rates": {"2024-01-02": {"KRW": 1300.5}}})
    assert fx[0]["per_usd"] == "1300.5" and fx[0]["label"] == LABEL
    pr = par_rows([{"casa": "blue", "compra": 10, "venta": 11, "fecha": "2011-01-03"},
                   {"casa": "oficial", "compra": 1, "venta": 1, "fecha": "2011-01-03"}])
    assert len(pr) == 1 and pr[0]["sell"] == "11.0"
    assert set(CANDLE_FIELDS) >= {"label", "source"} and "label" in FX_FIELDS and "label" in PAR_FIELDS
    # new venues: parse each venue's payload shape exactly as reported
    bm = f_btcmarkets("1d", 0, fetch=lambda u: [
        ["2026-09-21T00:00:00.000000Z", "1.4", "1.5", "1.3", "1.44", "10"]], now=now)
    assert bm == [(1789948800, 1.44)], bm
    wz = f_wazirx("1d", 1789900000, fetch=lambda u: [[1789948800, 100, 101, 99, 100.03, 5], [1790035200, 100, 100, 100, 100, 0]], now=now)
    assert wz == [(1789948800, 100.03)], wz
    dc = f_coindcx("1d", 1789900000, fetch=lambda u: [{"close": 99.5, "volume": 7, "time": 1789948800000},
                                                {"close": 99.5, "volume": 0, "time": 1790035200000}], now=now)
    assert dc == [(1789948800, 99.5)], dc
    ib = f_indodax("1d", 1789900000, fetch=lambda u: [{"Time": 1789948800, "Close": 16000}], now=now)
    assert ib == [(1789948800, 16000.0)], ib
    bs = f_bitso("1d", 1789900000, fetch=lambda u: {"payload": [
        {"bucket_start_time": 1789948800000, "last_rate": "18.5"}]}, now=now)
    assert bs == [(1789948800, 18.5)], bs
    cb = cbc_rows([{"date": "2024-01-02", "base": "USD", "quote": "TWD", "rate": 30.866}])
    assert cb[0]["per_usd"] == "30.866" and cb[0]["ccy"] == "TWD" and cb[0]["label"] == LABEL
    print("  ALL SELFTESTS PASSED")


def main():
    ap = argparse.ArgumentParser(description="history layer: reported, not observed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--only", help="comma list: venue names, FX, Parallel")
    ap.add_argument("--hourly-since", default=DEFAULT_HOURLY_SINCE)
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")
    run(a.only.split(",") if a.only else None, a.hourly_since, a.dry_run)


if __name__ == "__main__":
    main()
