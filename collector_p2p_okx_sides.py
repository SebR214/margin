#!/usr/bin/env python3
"""
margin.wiki P2P collector -- OKX ads counted per side (SEB-464).

collector_p2p_okx.py stores n_ads as buy plus sell together, so we cannot tell
whether ten people are selling. This file counts each side on its own for the
five countries withheld today for too few sellers: Angola, Botswana, Ghana,
Lebanon and South Africa.

Additive and inert. It does not import or change collector_p2p_okx.py and it
writes only the sidecar data/p2p_okx_sides.csv. Nothing reads it yet.

Same method as collector_p2p_okx.py: the first page (20 ads) of each side, kept
only if a USD 500 ticket, in local money off one FX snapshot, sits inside the
ad's own order-size range.

Names follow that file. n_buy_ads counts the ads a buyer of USDT can take (OKX
side=sell, the ask). n_sell_ads counts the ads a seller of USDT can take (OKX
side=buy, the bid). buy_median is the median ask price over the first 10 of
those ads, as in the main file.

A failed pull is a row with source_ok=false and the reason. Exits non-zero only
when every currency failed.

Usage:
  python3 collector_p2p_okx_sides.py            # one pull, append the sidecar
  python3 collector_p2p_okx_sides.py --verify   # one live pull, print, write nothing
"""
import argparse
import csv
import datetime as dt
import os
import statistics
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "p2p_okx_sides.csv")
FIELDS = ["ts_utc", "ccy", "n_buy_ads", "n_sell_ads", "buy_median", "source_ok", "error"]
CURRENCIES = ["AOA", "BWP", "GHS", "LBP", "ZAR"]
BOOKS_URL = "https://www.okx.com/v3/c2c/tradingOrders/books"
FX_URL = "https://open.er-api.com/v6/latest/USD"
UNSUPPORTED_CODE = 17007
FILTER_USD = 500
ROWS = 10
HTTP_TIMEOUT = 25
REQUEST_GAP = 0.7
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0
UA = {"User-Agent": "margin.wiki p2p-collector-okx-sides/1.0 (+https://margin.wiki)"}


def _num(x, allow_zero=False):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if (v > 0 or (allow_zero and v == 0)) else None


def qualifying_prices(ads, filter_local):
    """Prices of ads whose own min and max order size span filter_local, in board order."""
    out = []
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        lo = _num(ad.get("quoteMinAmountPerOrder"), True)
        hi = _num(ad.get("quoteMaxAmountPerOrder"), True)
        price = _num(ad.get("price"))
        if lo is None or hi is None or price is None:
            continue
        if lo <= filter_local <= hi:
            out.append(price)
    return out


_last = [0.0]


def get_json(url):
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_BACKOFF * attempt)
        wait = REQUEST_GAP - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def books_url(ccy, side):
    return (f"{BOOKS_URL}?side={side}&paymentMethod=all&userType=all"
            f"&baseCurrency=usdt&quoteCurrency={ccy.lower()}"
            f"&currentPage=1&numberPerPage=20")


def fetch_fx():
    rates = (requests.get(FX_URL, timeout=HTTP_TIMEOUT, headers=UA).json().get("rates")) or {}
    if not rates:
        raise ValueError("er-api returned no rates")
    return {k: float(v) for k, v in rates.items()}


def build_rows(ts, currencies, fx, get=None):
    """One row per currency. Returns (rows, n_ok)."""
    get = get or get_json
    rows, n_ok = [], 0
    for ccy in currencies:
        row = {"ts_utc": ts, "ccy": ccy, "n_buy_ads": "", "n_sell_ads": "",
               "buy_median": "", "source_ok": False, "error": ""}
        try:
            fx_mid = fx.get(ccy)
            if not fx_mid:
                raise ValueError(f"no FX mid for {ccy}")
            filter_local = FILTER_USD * fx_mid
            sp = get(books_url(ccy, "sell"))
            if sp.get("code") == UNSUPPORTED_CODE:
                raise ValueError(f"unsupported currency (OKX code {UNSUPPORTED_CODE})")
            bp = get(books_url(ccy, "buy"))
            if bp.get("code") == UNSUPPORTED_CODE:
                raise ValueError(f"unsupported currency (OKX code {UNSUPPORTED_CODE})")
            asks = qualifying_prices((sp.get("data") or {}).get("sell") or [], filter_local)
            bids = qualifying_prices((bp.get("data") or {}).get("buy") or [], filter_local)
            row["n_buy_ads"], row["n_sell_ads"] = len(asks), len(bids)
            if asks:
                row["buy_median"] = round(statistics.median(asks[:ROWS]), 8)
            row["source_ok"] = True
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            row["n_buy_ads"] = row["n_sell_ads"] = ""
            row["error"] = f"{type(e).__name__}:{e}"[:300]
        rows.append(row)
    return rows, n_ok


def append(rows, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        fx = fetch_fx()
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] FX snapshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        fx = {}
    rows, n_ok = build_rows(ts, CURRENCIES, fx)
    if not args.verify:
        append(rows)  # persistence before display
    for r in rows:
        print(r)
    if n_ok == 0:
        print("TOTAL BLACKOUT: no currency read", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
