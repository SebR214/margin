#!/usr/bin/env python3
"""A live official rate beside er-api (SEB-310 item 3). Collected, compared, NOT published as the rate.

open.er-api.com updates once a day (00:02 UTC), so for most of every day the rate we divide by is hours old. This collector
reads an intraday rate for every currency we price, from a source that is not one of the apps we measure, and stores it beside
the er-api rate. Nothing reads data/fx_live.csv yet: the published rate does not change. After seven days the comparison
(per currency, the median gap to er-api, which rejected quotes would pass, which currencies the rate check flags) goes to
Seb, who decides whether to switch.

    data/fx_live.csv
    ts_utc,ccy,rate_per_usd,source,source_ts_utc,er_api_rate,gap_pct,source_ok,error

One row per currency per run. A failed read is a row with source_ok=false and the reason, never a gap and never a copied
rate. The source's own timestamp is stored as the source gave it (source_ts_utc); our clock is ts_utc.

Sources, tried in this order, keyless:
  1. Yahoo Finance spark endpoint, one call for up to 20 currencies ("PHP=X" is PHP per US dollar), hourly closes of today.
     It rate-limits clients that ask a lot (HTTP 429), so one call per batch, a pause between batches.
  2. Google Finance quote page, one page per currency still missing ("USD-PHP"), the rate and its timestamp read out of the
     page's own data block. Heavy (1.5 MB a page), so only for what Yahoo did not answer.
The gap to er-api is stored with every row (gap_pct). A rate more than five times or less than a fifth of er-api's is a
broken read, not news: source_ok=false. Smaller gaps are kept, because they are the finding: for Sudan on 21 Oct the live
rate was 601.5 against er-api's 449.2, and er-api is the one that is wrong.

New sources go through tools/probe_source.py and seven days of quarantine; this file only writes data/fx_live.csv, which feeds
nothing, so it is quarantined by construction until Seb switches something to read it.

Usage:  python3 collector_official_live.py             # one pass, appends to data/fx_live.csv
        python3 collector_official_live.py --selftest   # parsers on fixtures, no network, writes nothing
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "fx_live.csv")
FX = os.path.join(HERE, "data", "fx_rates.csv")
HEADER = ["ts_utc", "ccy", "rate_per_usd", "source", "source_ts_utc", "er_api_rate", "gap_pct", "source_ok", "error"]
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
YAHOO = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%s&range=1d&interval=1h"
GOOGLE = "https://www.google.com/finance/quote/USD-%s"
TIMEOUT = 25
BATCH = 20
MAX_RATIO = 5.0           # more than five times (or under a fifth of) er-api's rate is a broken read, not a rate


def tracked_currencies():
    """The currencies in the newest er-api read, USD aside: the ones the index divides by."""
    rows = list(csv.DictReader(open(FX, newline="")))
    last = max(r["ts_utc"] for r in rows)
    return sorted({r["ccy"] for r in rows if r["ts_utc"] == last and r["ccy"] != "USD"}), {
        r["ccy"]: float(r["fx_mid_per_usd"]) for r in rows if r["ts_utc"] == last and r["fx_mid_per_usd"]}


def iso(epoch):
    return dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_yahoo(payload):
    """spark payload -> {ccy: (rate, source_ts_utc)}. The newest hourly close that is a number."""
    out = {}
    for r in (payload.get("spark", {}).get("result") or []):
        sym = r.get("symbol", "")
        if not sym.endswith("=X") or len(sym) != 5:
            continue
        try:
            resp = r["response"][0]
            pts = [(t, c) for t, c in zip(resp.get("timestamp") or [], resp["indicators"]["quote"][0]["close"]) if c]
            if pts:
                out[sym[:3]] = (float(pts[-1][1]), iso(pts[-1][0]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def parse_google(html, ccy):
    """The quote block: ["USD / PHP",3,null,[63.4199862,...],null,<previous close>,...,[<epoch>],...,"USD-PHP"] -> (rate, ts)."""
    m = re.search(r'"USD / %s",\d+,null,\[([0-9.]+),[^\]]*\],null,[0-9.]+,null,null,null,\[(\d{10})\]' % re.escape(ccy), html)
    if not m:
        raise ValueError("quote block not found in the page")
    return float(m.group(1)), iso(m.group(2))


def fetch_yahoo(ccys):
    import requests            # imported here so the offline self-test runs without it
    got, err = {}, {}
    for i in range(0, len(ccys), BATCH):
        batch = ccys[i:i + BATCH]
        try:
            r = requests.get(YAHOO % ",".join(c + "=X" for c in batch), timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            got.update(parse_yahoo(r.json()))
        except Exception as e:
            for c in batch:
                err[c] = "yahoo:%s:%s" % (type(e).__name__, str(e)[:80])
        time.sleep(2)
    return got, err


def fetch_google(ccy):
    import requests
    r = requests.get(GOOGLE % ccy, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    return parse_google(r.text, ccy)


def row(ts, ccy, rate, source, src_ts, er, err=""):
    ok = rate is not None and not err
    base = er.get(ccy)
    gap = round((rate / base - 1) * 100, 3) if (rate is not None and base) else ""
    if ok and base and not (1 / MAX_RATIO < rate / base < MAX_RATIO):
        ok, err = False, "implausible against er-api: %s vs %s" % (rate, base)
    return [ts, ccy, rate if rate is not None else "", source, src_ts or "", base or "", gap, ok, err]


def collect():
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ccys, er = tracked_currencies()
    rows = []
    got, yerr = fetch_yahoo(ccys)
    for c in ccys:
        if c in got:
            rows.append(row(ts, c, got[c][0], "yahoo", got[c][1], er))
    for c in ccys:
        if c in got:
            continue
        try:
            rate, sts = fetch_google(c)
            rows.append(row(ts, c, rate, "google", sts, er))
        except Exception as e:
            why = "%s; google:%s:%s" % (yerr.get(c, "yahoo:no quote for this currency"), type(e).__name__, str(e)[:80])
            rows.append(row(ts, c, None, "none", "", er, why))
        time.sleep(1)
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as fh:                # written before anything is printed
        w = csv.writer(fh)
        if new:
            w.writerow(HEADER)
        w.writerows(rows)
    ok = sum(1 for r in rows if r[7] is True)
    print("fx_live: %d of %d currencies read (%s)" % (ok, len(rows), ", ".join(sorted({r[3] for r in rows if r[7] is True})) or "none"))
    return 0 if ok else 1                                 # nothing read at all fails loud


def selftest():
    y = {"spark": {"result": [
        {"symbol": "PHP=X", "response": [{"timestamp": [1792590000, 1792593600], "indicators": {"quote": [{"close": [63.1, None]}]}}]},
        {"symbol": "SDG=X", "response": [{"timestamp": [1792590000], "indicators": {"quote": [{"close": [None]}]}}]}]}}
    got = parse_yahoo(y)
    assert got == {"PHP": (63.1, iso(1792590000))}, got
    html = 'x"USD / PHP",3,null,[63.4199862,0.31,0.49,4,4,2],null,63.1095,null,null,null,[1792597939],null,0,"/g/x"'
    assert parse_google(html, "PHP") == (63.4199862, iso(1792597939))
    try:
        parse_google("no block", "PHP")
        raise AssertionError("a page without the block must raise")
    except ValueError:
        pass
    er = {"PHP": 63.0}
    r = row("t", "PHP", 63.4, "google", "s", er)
    assert r[7] is True and r[6] == round((63.4 / 63.0 - 1) * 100, 3), r
    assert row("t", "SDG", 601.5, "google", "s", {"SDG": 449.23})[7] is True, "a one-third gap is the finding, kept"
    r = row("t", "PHP", 630.0, "google", "s", er)
    assert r[7] is False and "implausible" in r[8], r
    assert row("t", "PHP", None, "none", "", er, "x")[7] is False
    print("collector_official_live self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
