#!/usr/bin/env python3
"""
margin.wiki FX collector -- the DENOMINATOR layer.

Every index figure is a price divided by an official exchange rate. Until now
that rate arrived inside each price row, which made it invisible: no record of
where it came from, no way to change source without touching frozen schemas,
and no way to publish a parallel rate beside it. This collector makes the
denominator a first-class record of its own.

    data/fx_rates.csv
    ts_utc,ccy,fx_mid_per_usd,source,managed_flag,parallel_rate_per_usd,parallel_source

WHAT THIS IS NOT. The brief asked for an intraday source. **There is not one
among the candidates, and three of the four are worse than what we already
use.** Measured from a US runner, 2026-09-10:

    open.er-api        166 currencies, 36/36 of ours, stamped 00:02 UTC daily
    frankfurter.app     29 currencies, 10/36 of ours, ECB daily fix, a day older
    frankfurter.dev     identical to frankfurter.app
    ECB reference feed  29 currencies, 10/36 of ours, the same daily fix
    exchangerate.host   refuses without an access key

frankfurter and the ECB feed ARE the same ECB daily fix, they cover essentially
no emerging market, and their stamp is the previous working day. So er-api stays
primary on both freshness and coverage, and this file records that choice per
row rather than leaving it implicit.

What DOES improve the denominator is a central bank where one publishes
directly. Argentina's BCRA publishes its reference rate (Comunicacion A 3500)
with no key, and a central bank outranks an aggregator by definition. Per-
currency overrides live in CENTRAL_BANKS and are applied before the general
sources.

PARALLEL RATES. For a managed currency the official rate is a policy number, so
where a public feed publishes the parallel rate it is recorded beside it --
never instead of it, never estimated, blank where no public source exists.

Usage:
  python3 collector_fx.py --verify     # one live pull, print, write nothing
  python3 collector_fx.py              # one pull, append data/fx_rates.csv
  python3 collector_fx.py --selftest   # offline, mocked sources
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

HTTP_TIMEOUT = 25
UA = {"User-Agent": "margin.wiki fx-collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "data", "fx_rates.csv")

FIELDS = ["ts_utc", "ccy", "fx_mid_per_usd", "source", "managed_flag",
          "parallel_rate_per_usd", "parallel_source"]

# Fallback order for the general sources. Measured cadence is DAILY for every
# one of them; the order is by freshness of stamp, then coverage.
SOURCES = [
    ("open.er-api", "https://open.er-api.com/v6/latest/USD"),
    ("frankfurter", "https://api.frankfurter.app/latest?base=USD"),
]

# A central bank publishing its own reference rate outranks any aggregator.
CENTRAL_BANKS = {
    "ARS": ("bcra",
            "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones"),
}

# Public parallel-rate feeds, no key. Only where one exists; never estimated.
PARALLEL = {
    "ARS": ("dolarapi.ar", "https://dolarapi.com/v1/dolares", "blue"),
    "VES": ("dolarapi.ve", "https://ve.dolarapi.com/v1/dolares", "paralelo"),
    "BOB": ("dolarapi.bo", "https://bo.dolarapi.com/v1/dolares", "binance"),
}

# Kept in step with METHODOLOGY, "The denominator, and where it is a policy
# number". Duplicated rather than imported so this collector stays independent
# of the emitters, the same rule the other collectors follow.
MANAGED = {"ARS", "VES", "LBP", "SDG", "DZD", "SYP", "IQD", "AFN", "MZN",
           "ETB", "NGN", "AOA", "UAH", "TND", "MMK", "ZWL"}


# ------------------------------------------------------------- pure core
def _f(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_erapi(d):
    return {k: v for k, v in (d.get("rates") or {}).items() if _f(v)}


def parse_frankfurter(d):
    return {k: v for k, v in (d.get("rates") or {}).items() if _f(v)}


def parse_bcra(d):
    """BCRA Comunicacion A 3500 reference rate, ARS per USD."""
    for row in ((d.get("results") or {}).get("detalle") or []):
        if row.get("codigoMoneda") == "USD":
            return _f(row.get("tipoCotizacion"))
    return None


def parse_dolarapi(d, casa):
    """Mid of the named house, or its average where no two sides are given."""
    if not isinstance(d, list):
        return None
    for row in d:
        if not isinstance(row, dict):
            continue
        name = (row.get("casa") or row.get("fuente") or "").lower()
        if name != casa:
            continue
        buy, sell = _f(row.get("compra")), _f(row.get("venta"))
        if buy and sell:
            return (buy + sell) / 2
        return _f(row.get("promedio")) or sell or buy
    return None


# ------------------------------------------------------------------ I/O
def get_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def build_rows(ts, currencies, fetch=get_json):
    """One row per currency. Never raises. Returns (rows, n_ok)."""
    general, errors = {}, {}
    for name, url in SOURCES:
        try:
            payload = fetch(url)
            general[name] = (parse_erapi(payload) if name == "open.er-api"
                             else parse_frankfurter(payload))
        except Exception as e:
            errors[name] = f"{type(e).__name__}:{e}"[:120]
            general[name] = {}

    banks = {}
    for ccy, (name, url) in CENTRAL_BANKS.items():
        try:
            banks[ccy] = (name, parse_bcra(fetch(url)))
        except Exception as e:
            errors[name] = f"{type(e).__name__}:{e}"[:120]

    par = {}
    for ccy, (name, url, casa) in PARALLEL.items():
        try:
            par[ccy] = (name, parse_dolarapi(fetch(url), casa))
        except Exception as e:
            errors[name] = f"{type(e).__name__}:{e}"[:120]

    rows, n_ok = [], 0
    for ccy in sorted(currencies):
        rate, source = None, ""
        bank = banks.get(ccy)
        if bank and bank[1]:
            rate, source = bank[1], bank[0]
        else:
            for name, _ in SOURCES:
                v = _f((general.get(name) or {}).get(ccy))
                if v:
                    rate, source = v, name
                    break
        p_rate, p_source = None, ""
        if ccy in par and par[ccy][1]:
            p_source, p_rate = par[ccy][0], par[ccy][1]
        rows.append({
            "ts_utc": ts, "ccy": ccy,
            "fx_mid_per_usd": round(rate, 8) if rate else None,
            "source": source, "managed_flag": ccy in MANAGED,
            "parallel_rate_per_usd": round(p_rate, 8) if p_rate else None,
            "parallel_source": p_source,
        })
        if rate:
            n_ok += 1
    return rows, n_ok, errors


def currencies_in_use():
    """Every currency any layer collects, read from the CSVs themselves."""
    seen = set()
    for name, col in (("basis.csv", "ccy"), ("p2p_basis.csv", "ccy")):
        path = os.path.join(HERE, "data", name)
        if not os.path.exists(path):
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                c = (row.get(col) or "").strip()
                if c:
                    seen.add(c)
    return seen


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
    os.makedirs(os.path.dirname(FX), exist_ok=True)
    new = not os.path.exists(FX)
    with open(FX, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return FX


def print_table(rows, errors):
    ok = [r for r in rows if r["fx_mid_per_usd"]]
    print(f"\n  Official rates   {rows[0]['ts_utc'][:16]}Z")
    print("  " + "-" * 68)
    by_source = {}
    for r in ok:
        by_source.setdefault(r["source"], []).append(r["ccy"])
    for src, ccys in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        print(f"  {src:14} {len(ccys):3} currencies")
    par = [r for r in rows if r["parallel_rate_per_usd"]]
    for r in par:
        gap = (r["parallel_rate_per_usd"] / r["fx_mid_per_usd"] - 1) * 100 \
            if r["fx_mid_per_usd"] else None
        print(f"  parallel  {r['ccy']}  official {r['fx_mid_per_usd']:>12,.4f}  "
              f"parallel {r['parallel_rate_per_usd']:>12,.4f}  "
              f"{'' if gap is None else f'{gap:+.2f}%'}  ({r['parallel_source']})")
    missing = [r["ccy"] for r in rows if not r["fx_mid_per_usd"]]
    if missing:
        print(f"  ! no rate for: {', '.join(missing)}")
    for k, v in errors.items():
        print(f"  ! {k}: {v}")
    print(f"  {len(ok)}/{len(rows)} currencies priced"
          f"{' -- TOTAL BLACKOUT' if not ok else ''}\n")


# -------------------------------------------------------------- selftest
ERAPI_FIXTURE = {"rates": {"ARS": 1515.1105, "KRW": 1339.0047, "SGD": 1.2728,
                           "VES": 813.74, "BOB": 12.15, "SDG": 544.4405}}
FRANK_FIXTURE = {"rates": {"KRW": 1340.0, "SGD": 1.2730}}
BCRA_FIXTURE = {"results": {"fecha": "2026-09-09", "detalle": [
    {"codigoMoneda": "ARS", "tipoCotizacion": 0.0},
    {"codigoMoneda": "USD", "descripcion": "DOLAR E.E.U.U.", "tipoCotizacion": 1513.5}]}}
DOLARAPI_AR = [{"casa": "oficial", "compra": 1485, "venta": 1535},
               {"casa": "blue", "compra": 1520, "venta": 1540}]
DOLARAPI_VE = [{"fuente": "oficial", "promedio": 827.7371},
               {"fuente": "paralelo", "promedio": 960.5}]
DOLARAPI_BO = [{"casa": "oficial", "compra": 12.64, "venta": 12.64},
               {"casa": "binance", "compra": 12.30, "venta": 12.40}]
TS_FIXTURE = "2026-09-10T00:00:00+00:00"


def _make_fetch(overrides=None):
    overrides = overrides or {}
    routes = {"open.er-api": ERAPI_FIXTURE, "frankfurter": FRANK_FIXTURE,
              "bcra.gob.ar": BCRA_FIXTURE, "ve.dolarapi": DOLARAPI_VE,
              "bo.dolarapi": DOLARAPI_BO, "dolarapi.com": DOLARAPI_AR}

    def fetch(url):
        for key, payload in routes.items():
            if key.split(".")[0] in url:
                val = overrides.get(key, payload)
                if isinstance(val, Exception):
                    raise val
                return val
        raise KeyError(url)
    return fetch


def selftest():
    assert parse_bcra(BCRA_FIXTURE) == 1513.5
    assert parse_bcra({"results": {"detalle": []}}) is None
    assert parse_erapi(ERAPI_FIXTURE)["ARS"] == 1515.1105
    assert parse_dolarapi(DOLARAPI_AR, "blue") == 1530.0
    assert parse_dolarapi(DOLARAPI_VE, "paralelo") == 960.5
    assert parse_dolarapi(DOLARAPI_AR, "nope") is None
    assert parse_dolarapi({}, "blue") is None
    print("  [ok] parsers read every source shape; malformed -> None")

    ccys = ["ARS", "KRW", "SGD", "VES", "BOB", "SDG", "XXX"]
    rows, n_ok, errs = build_rows(TS_FIXTURE, ccys, fetch=_make_fetch())
    by = {r["ccy"]: r for r in rows}
    # a central bank outranks the aggregator for its own currency
    assert by["ARS"]["source"] == "bcra" and by["ARS"]["fx_mid_per_usd"] == 1513.5
    assert by["KRW"]["source"] == "open.er-api"
    # a currency no source carries is a blank row, never a guess
    assert by["XXX"]["fx_mid_per_usd"] is None and by["XXX"]["source"] == ""
    assert n_ok == 6, n_ok
    print("  [ok] central bank outranks the aggregator; unknown currency -> blank")

    assert by["ARS"]["parallel_rate_per_usd"] == 1530.0
    assert by["VES"]["parallel_rate_per_usd"] == 960.5
    assert by["SDG"]["parallel_rate_per_usd"] is None, "no public feed -> blank"
    assert by["SDG"]["managed_flag"] is True and by["SGD"]["managed_flag"] is False
    print("  [ok] parallel rate only where a public feed exists; managed flag set")

    # the primary failing falls through to the next source, per currency
    rows_f, n_f, errs_f = build_rows(
        TS_FIXTURE, ["KRW", "ARS"], fetch=_make_fetch({"open.er-api": RuntimeError("503")}))
    kf = {r["ccy"]: r for r in rows_f}
    assert kf["KRW"]["source"] == "frankfurter" and kf["KRW"]["fx_mid_per_usd"] == 1340.0
    assert kf["ARS"]["source"] == "bcra", "central bank unaffected by aggregator outage"
    assert "open.er-api" in errs_f
    print("  [ok] a dead source falls through to the next, and is recorded")

    rows_d, n_d, _ = build_rows(TS_FIXTURE, ["KRW"], fetch=_make_fetch(
        {"open.er-api": RuntimeError("x"), "frankfurter": RuntimeError("y")}))
    assert n_d == 0 and rows_d[0]["fx_mid_per_usd"] is None
    print("  [ok] every source down -> blank rows, never an invented rate")

    assert set(FIELDS) >= set(rows[0])
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "fx.csv")
        assert captured_this_hour(p, "ts_utc") is False
        now = dt.datetime(2026, 9, 10, 14, 5, tzinfo=dt.timezone.utc)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "ccy"]); w.writeheader()
            w.writerow({"ts_utc": "2026-09-10T13:05:00+00:00", "ccy": "ARS"})
        assert captured_this_hour(p, "ts_utc", now) is False, "prior hour"
        with open(p, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=["ts_utc", "ccy"]).writerow(
                {"ts_utc": "2026-09-10T14:05:00+00:00", "ccy": "ARS"})
        assert captured_this_hour(p, "ts_utc", now) is True
    print("  [ok] schema covers every field; one capture per UTC hour\n")
    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki FX collector")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    if not a.verify and captured_this_hour(FX, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {FX}, nothing to do")
        return

    ccys = currencies_in_use()
    if not ccys:
        print("  [error] no currencies found in data/*.csv", file=sys.stderr)
        sys.exit(1)
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    rows, n_ok, errors = build_rows(ts, ccys)

    # PERSIST FIRST, DISPLAY SECOND.
    if not a.verify:
        append(rows)
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows, errors)
    if a.verify:
        return
    print(f"  appended -> {FX}\n")
    if n_ok == 0:
        print("  [error] TOTAL BLACKOUT -- no official rate from any source",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
