#!/usr/bin/env python3
"""
margin.wiki provider collector -- quotes from the providers themselves.

Until now every competitor quote came from ONE source: the Wise comparison API.
That is a good source and it is not a neutral one -- it is one company's choice
of who counts as a competitor, and it does not include everybody. This collector
asks providers directly, where they publish a public quote.

    data/provider_quotes.csv
    ts_utc,corridor,size_src,provider,rate,fee_src,received_dst,cost_bps,
    source,source_ok,error

THE PRECEDENCE RULE. Where a provider publishes its own rate, that is the number
used. Where it does not, the comparison API stands in. A provider quoting itself
is the more direct evidence, and every published row says which it is, so no
reader has to wonder and no source is being called wrong.

Cost is measured the same way as everywhere else in this repo: how far below the
mid-market rate the recipient ends up, in bps of the amount sent. Fees and rate
margin are one number, because that is what a sender experiences.

    cost_bps = (1 - received / (amount_sent * mid)) * 10_000

WHO IS HERE, AND WHO IS NOT.
  Instarem   public quote API. The account id is per source country, so only
             the two verified from Instarem's own pages are configured -- SG
             and AU. NZ and US are left blank rather than guessed.
  Airwallex  public indicative-quote API, all four corridors.
  Revolut    publishes a live rate on its currency-converter page, but the
             quote API needs auth (401) and the page returns 403 to anything
             that is not a browser. Collecting it would mean running a headless
             browser in CI. Not done, and recorded here rather than omitted.

Usage:
  python3 collector_providers.py --verify     # live pull, print, write nothing
  python3 collector_providers.py              # append data/provider_quotes.csv
  python3 collector_providers.py --selftest   # offline
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

HTTP_TIMEOUT = 20
REQUEST_GAP = 0.4
UA = {"User-Agent": "margin.wiki provider-collector/1.0 (+https://margin.wiki)",
      "accept": "application/json"}
HERE = os.path.dirname(os.path.abspath(__file__))
QUOTES = os.path.join(HERE, "data", "provider_quotes.csv")
FX_URL = "https://open.er-api.com/v6/latest/USD"

FIELDS = ["ts_utc", "corridor", "size_src", "provider", "rate", "fee_src",
          "received_dst", "cost_bps", "source", "source_ok", "error"]

LADDER = [200, 1000, 5000, 25000, 50000]

# Instarem's quote needs the account id for the SOURCE country. Both of these
# were read from Instarem's own locale pages (en-sg and en-au) rather than
# guessed; a corridor absent from this map is simply not asked.
INSTAREM_ACCOUNT = {
    "SGD->PHP": ("SG", "93"),
    "AUD->PHP": ("AU", "135"),
}

CORRIDOR_CCY = {
    "SGD->PHP": ("SGD", "PHP"), "AUD->PHP": ("AUD", "PHP"),
    "NZD->PHP": ("NZD", "PHP"), "USD->MXN": ("USD", "MXN"),
}


# ------------------------------------------------------------- pure core
def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def cost_bps(received, sent, mid):
    """How far below mid-market the recipient lands, in bps of the amount sent."""
    if not received or not sent or not mid:
        return None
    return round((1 - received / (sent * mid)) * 1e4, 2)


def parse_airwallex(d, sent):
    """{"ccyPair","clientRate","buyAmount","sellAmount"} -> (rate, fee, received).

    Airwallex quotes a rate and applies its fee as a percentage the caller
    passes in; the site's own widget passes feePercent=0, so this is the rate
    before any transfer fee. Recorded as a rate with a zero fee and labelled
    "indicative", which is Airwallex's own word for it.
    """
    rate = _f(d.get("clientRate"))
    recv = _f(d.get("buyAmount"))
    if rate and not recv:
        recv = rate * sent
    return (rate, 0.0, recv)


def parse_instarem(d, sent):
    """{"data":{"fx_rate","destination_amount","transaction_fee_amount"}}."""
    x = (d.get("data") or {}) if isinstance(d, dict) else {}
    rate = _f(x.get("fx_rate"))
    fee = _f(x.get("transaction_fee_amount"))
    recv = _f(x.get("destination_amount"))
    if rate and recv is None:
        recv = rate * sent
    return (rate, 0.0 if fee is None else fee, recv)


# ------------------------------------------------------------------ I/O
_last = [0.0]


def _pace():
    wait = REQUEST_GAP - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()


def get_json(url):
    _pace()
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_mids(fetch=get_json):
    d = fetch(FX_URL)
    rates = d.get("rates") or {}
    if not rates:
        raise ValueError("er-api returned no rates")
    return {k: float(v) for k, v in rates.items()}


def airwallex_url(src, dst, amount):
    return ("https://www.airwallex.com/api/fx/fxRate/indicativeQuote"
            f"?sellAmount={amount}&sellCcy={src}&buyCcy={dst}&feePercent=0")


def instarem_url(corridor, src, dst, amount):
    cc, acct = INSTAREM_ACCOUNT[corridor]
    return ("https://www.instarem.com/api/v1/public/transaction/computed-value"
            f"?source_currency={src}&destination_currency={dst}"
            f"&instarem_bank_account_id={acct}&country_code={cc}"
            f"&source_amount={amount}")


# ------------------------------------------------------------- collection
def _row(ts, corridor, size, provider, source):
    return {"ts_utc": ts, "corridor": corridor, "size_src": size,
            "provider": provider, "rate": None, "fee_src": None,
            "received_dst": None, "cost_bps": None, "source": source,
            "source_ok": False, "error": ""}


def build_rows(ts, corridors, mids, fetch=get_json):
    """One row per corridor per size per provider. Never raises."""
    rows, n_ok = [], 0
    for corridor in corridors:
        src, dst = CORRIDOR_CCY[corridor]
        mid = None
        if mids.get(src) and mids.get(dst):
            mid = mids[dst] / mids[src]
        for size in LADDER:
            jobs = [("Airwallex", "airwallex.com",
                     airwallex_url(src, dst, size), parse_airwallex)]
            if corridor in INSTAREM_ACCOUNT:
                jobs.append(("Instarem", "instarem.com",
                             instarem_url(corridor, src, dst, size), parse_instarem))
            for provider, source, url, parse in jobs:
                row = _row(ts, corridor, size, provider, source)
                try:
                    if mid is None:
                        raise ValueError(f"no mid for {src}->{dst}")
                    rate, fee, recv = parse(fetch(url), size)
                    if not rate or not recv:
                        raise ValueError("no usable quote")
                    row.update(rate=round(rate, 8), fee_src=fee,
                               received_dst=round(recv, 4),
                               cost_bps=cost_bps(recv, size, mid), source_ok=True)
                    n_ok += 1
                except Exception as e:
                    row["error"] = f"{type(e).__name__}:{e}"[:300]
                rows.append(row)
    return rows, n_ok


def utc_hour(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def captured_this_hour(path, ts_field, now=None):
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
    os.makedirs(os.path.dirname(QUOTES), exist_ok=True)
    new = not os.path.exists(QUOTES)
    with open(QUOTES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return QUOTES


def print_table(rows):
    print(f"\n  Quotes from the providers themselves   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 70)
    cur = None
    for r in rows:
        if r["corridor"] != cur:
            cur = r["corridor"]
            print(f"  {cur}")
        ok = f"{r['cost_bps']:>8.2f} bps" if r["source_ok"] else "      --   "
        print(f"     {r['size_src']:>7,}  {r['provider']:<12}{ok}"
              f"   rate {r['rate'] if r['rate'] else '--'}"
              f"{'' if r['source_ok'] else '  ! ' + r['error'][:44]}")
    bad = [r for r in rows if not r["source_ok"]]
    print("  " + "-" * 70)
    print(f"  {len(rows) - len(bad)}/{len(rows)} quotes"
          f"{' -- TOTAL BLACKOUT' if len(bad) == len(rows) else ''}\n")


# -------------------------------------------------------------- selftest
AWX_FIXTURE = {"ccyPair": "SGDPHP", "clientRate": 49.367261,
               "buyAmount": 49367.26, "sellAmount": 1000.00}
INSTA_FIXTURE = {"success": True, "data": {
    "fx_rate": 49.4144, "destination_amount": 49414.4,
    "transaction_fee_amount": 0, "source_currency": "SGD",
    "destination_currency": "PHP"}}
MIDS = {"SGD": 1.2728, "PHP": 62.9455, "AUD": 1.5281, "NZD": 1.6902,
        "USD": 1.0, "MXN": 18.35}
TS = "2026-09-10T10:00:00+00:00"


def _make_fetch(overrides=None):
    overrides = overrides or {}

    def fetch(url):
        key = "airwallex" if "airwallex" in url else "instarem"
        val = overrides.get(key, AWX_FIXTURE if key == "airwallex" else INSTA_FIXTURE)
        if isinstance(val, Exception):
            raise val
        return val
    return fetch


def selftest():
    assert parse_airwallex(AWX_FIXTURE, 1000) == (49.367261, 0.0, 49367.26)
    assert parse_instarem(INSTA_FIXTURE, 1000) == (49.4144, 0.0, 49414.4)
    assert parse_instarem({}, 1000) == (None, 0.0, None)
    assert parse_airwallex({}, 1000) == (None, 0.0, None)
    print("  [ok] both parsers read their real payload; malformed -> no quote")

    mid = MIDS["PHP"] / MIDS["SGD"]
    assert abs(cost_bps(49414.4, 1000, mid) - 8.25) < 3.0
    assert cost_bps(None, 1000, mid) is None and cost_bps(1.0, 0, mid) is None
    print("  [ok] cost is bps below mid-market, None-safe")

    rows, n_ok = build_rows(TS, ["SGD->PHP", "USD->MXN"], MIDS, fetch=_make_fetch())
    # SGD->PHP has Instarem configured, USD->MXN does not
    assert len(rows) == 5 * 2 + 5 * 1 == 15, len(rows)
    assert n_ok == 15, n_ok
    provs = {(r["corridor"], r["provider"]) for r in rows}
    assert ("USD->MXN", "Instarem") not in provs, "unconfigured corridor is not asked"
    assert ("SGD->PHP", "Instarem") in provs
    print("  [ok] a corridor with no verified account id is not asked, not guessed")

    rows_e, n_e = build_rows(TS, ["SGD->PHP"], MIDS,
                             fetch=_make_fetch({"instarem": RuntimeError("503")}))
    ins = [r for r in rows_e if r["provider"] == "Instarem"]
    assert all(not r["source_ok"] and "503" in r["error"] for r in ins)
    assert n_e == 5, n_e
    print("  [ok] one provider down isolates to its own rows")

    rows_m, n_m = build_rows(TS, ["SGD->PHP"], {"SGD": 1.27}, fetch=_make_fetch())
    assert n_m == 0 and all("no mid" in r["error"] for r in rows_m)
    print("  [ok] a missing mid degrades its corridor, never invents a rate")

    assert set(FIELDS) >= set(rows[0])
    print("  [ok] schema covers every field\n")
    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki provider collector")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    if not a.verify and captured_this_hour(QUOTES, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {QUOTES}, nothing to do")
        return

    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        mids = fetch_mids()
    except Exception as e:
        print(f"  [warn] mid snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        mids = {}
    rows, n_ok = build_rows(ts, sorted(CORRIDOR_CCY), mids)

    # PERSIST FIRST, DISPLAY SECOND.
    if not a.verify:
        append(rows)
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)
    if a.verify:
        return
    print(f"  appended -> {QUOTES}\n")
    if n_ok == 0:
        print("  [error] TOTAL BLACKOUT -- no provider quoted", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
