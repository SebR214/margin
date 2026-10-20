#!/usr/bin/env python3
"""
margin.wiki US-to-PH Philippines-side leg collector (Coins.ph).

This collector fetches the bid and ask prices for the USDT/PHP trading pair
from Coins.ph API, calculates the spread in basis points, and appends the data
to data/us_ph_phleg.csv.

Usage:
  python3 collector_us_ph_phleg.py --verify     # one live pull, print, write nothing
  python3 collector_us_ph_phleg.py              # one pull, append data/us_ph_phleg.csv
  python3 collector_us_ph_phleg.py --selftest   # offline, mocked sources
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
UA = {"User-Agent": "margin.wiki phleg-collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data", "us_ph_phleg.csv")

FIELDS = ["ts_utc", "bid_php_per_usdt", "ask_php_per_usdt", "spread_bps"]


# ------------------------------------------------------------------ I/O
def get_json(url):
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def fetch_coinsph():
    """Fetch bid and ask prices from Coins.ph for USDT/PHP."""
    url = "https://api.pro.coins.ph/openapi/quote/v1/ticker/bookTicker?symbol=USDTPHP"
    data = get_json(url)
    bid = data.get("bidPrice")
    ask = data.get("askPrice")
    return bid, ask


def build_row(ts, fetch_fn=fetch_coinsph):
    """Build one row of data. Returns the row dict or None on failure."""
    try:
        bid_str, ask_str = fetch_fn()
        bid = float(bid_str)
        ask = float(ask_str)
        if bid <= 0 or ask <= 0 or bid > ask:
            return None
        spread_bps = (ask / bid - 1) * 10000
        return {
            "ts_utc": ts,
            "bid_php_per_usdt": round(bid, 8),
            "ask_php_per_usdt": round(ask, 8),
            "spread_bps": round(spread_bps, 2)
        }
    except Exception:
        return None


def append_row(row):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    new = not os.path.exists(DATA_FILE)
    with open(DATA_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
    return DATA_FILE


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


def utc_hour(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).replace(
        minute=0, second=0, microsecond=0)


def print_row(row):
    if row is None:
        print("  [error] failed to fetch data")
        return
    print(f"\n  {row['ts_utc'][:16]}Z")
    print(f"  Bid: {row['bid_php_per_usdt']:.8f} PHP/USDT")
    print(f"  Ask: {row['ask_php_per_usdt']:.8f} PHP/USDT")
    print(f"  Spread: {row['spread_bps']:.2f} bps\n")


# -------------------------------------------------------------- selftest
def selftest():
    def mock_fetch():
        return "55.5", "55.6111"

    ts = "2026-09-10T00:00:00+00:00"
    row = build_row(ts, fetch_fn=mock_fetch)
    assert row is not None
    assert row["bid_php_per_usdt"] == 55.5
    assert row["ask_php_per_usdt"] == 55.6111
    assert row["spread_bps"] == 200.02  # (55.6111/55.5 - 1) * 10000
    print("  [ok] row built correctly with sample data")

    def mock_fetch_bad():
        return "0", "55.6111"

    row_bad = build_row(ts, fetch_fn=mock_fetch_bad)
    assert row_bad is None
    print("  [ok] invalid data returns None")

    def mock_fetch_exception():
        raise RuntimeError("API error")

    row_exc = build_row(ts, fetch_fn=mock_fetch_exception)
    assert row_exc is None
    print("  [ok] exception returns None")

    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="margin.wiki US-to-PH Philippines-side leg collector")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
    if requests is None:
        sys.exit("pip install requests")

    if not a.verify and captured_this_hour(DATA_FILE, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {DATA_FILE}, nothing to do")
        return

    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    row = build_row(ts)

    if row is None:
        if a.verify:
            print("  [error] failed to fetch data")
        else:
            print(f"  [error] failed to fetch data -> no row written to {DATA_FILE}")
        return

    # PERSIST FIRST, DISPLAY SECOND.
    if not a.verify:
        append_row(row)
        print(f"  appended -> {DATA_FILE}")
    print_row(row)


if __name__ == "__main__":
    main()
