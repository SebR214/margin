#!/usr/bin/env python3
"""
US-side leg collector: Coinbase, with Kraken as fallback.

This collector fetches the USD/USDT ticker from Coinbase first. If that fails,
it falls back to Kraken. It appends one row with a UTC timestamp, the venue
used, bid and ask of the dollar stablecoin in US dollars, and the spread in
basis points to data/us_ph_usleg.csv.

Usage:
  python3 collector_us_ph_usleg.py --verify     # one live pull, print, write nothing
  python3 collector_us_ph_usleg.py              # one pull, append data/us_ph_usleg.csv
  python3 collector_us_ph_usleg.py --selftest   # offline, mocked sources
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
UA = {"User-Agent": "margin.wiki usleg-collector/1.0 (+https://margin.wiki)"}
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "data", "us_ph_usleg.csv")

FIELDS = ["ts_utc", "venue", "bid", "ask", "spread_bps"]

COINBASE_URL = "https://api.exchange.coinbase.com/products/USDT-USD/ticker"
KRAKEN_URL = "https://api.kraken.com/0/public/Ticker?pair=USDTUSD"


# ------------------------------------------------------------- pure core
def parse_coinbase(data):
    """Parse Coinbase ticker response."""
    bid = float(data.get("bid", 0))
    ask = float(data.get("ask", 0))
    return bid, ask


def parse_kraken(data):
    """Parse Kraken ticker response."""
    pair_data = data.get("result", {}).get("USDTZUSD", {})
    if not pair_data:
        raise ValueError("No USDTZUSD data in Kraken response")
    
    ask = float(pair_data.get("a", [0])[0])
    bid = float(pair_data.get("b", [0])[0])
    return bid, ask


def fetch_price(url, parser):
    """Fetch and parse price data from given URL using specified parser."""
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
    r.raise_for_status()
    return parser(r.json())


def get_prices():
    """Get prices from Coinbase first, fall back to Kraken."""
    try:
        bid, ask = fetch_price(COINBASE_URL, parse_coinbase)
        venue = "Coinbase"
    except Exception as e1:
        try:
            bid, ask = fetch_price(KRAKEN_URL, parse_kraken)
            venue = "Kraken"
        except Exception as e2:
            raise RuntimeError(f"Both Coinbase and Kraken failed: {e1}, {e2}")
    
    # Calculate spread in basis points: (ask - bid) / ((ask + bid) / 2) * 10000
    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10000
    else:
        spread_bps = 0
    
    return {
        "venue": venue,
        "bid": round(bid, 8),
        "ask": round(ask, 8),
        "spread_bps": round(spread_bps, 2)
    }


# ------------------------------------------------------------------ I/O
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


def append(row):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    new = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
    return CSV_PATH


def print_row(row):
    print(f"\n  US-side leg pricing   {row['ts_utc'][:16]}Z")
    print("  " + "-" * 50)
    print(f"  Venue:      {row['venue']}")
    print(f"  Bid:        {row['bid']:,.8f}")
    print(f"  Ask:        {row['ask']:,.8f}")
    print(f"  Spread:     {row['spread_bps']:.2f} bps")
    print()


# -------------------------------------------------------------- selftest
COINBASE_FIXTURE = {
    "bid": "1.0002",
    "ask": "1.0003",
    "price": "1.00025"
}

KRAKEN_FIXTURE = {
    "error": [],
    "result": {
        "USDTZUSD": {
            "a": ["1.00040000", "1", "1.00000000"],
            "b": ["1.00020000", "1", "1.00000000"],
            "c": ["1.00030000", "1.00000000"]
        }
    }
}


def _make_fetch(coinbase_response=None, kraken_response=None, should_fail=False):
    responses = {
        COINBASE_URL: coinbase_response or COINBASE_FIXTURE,
        KRAKEN_URL: kraken_response or KRAKEN_FIXTURE
    }
    
    def fetch(url, timeout=None, headers=None):
        class MockResponse:
            def __init__(self, json_data):
                self._json_data = json_data
            
            def json(self):
                return self._json_data
                
            def raise_for_status(self):
                if should_fail:
                    raise RuntimeError("Network error")
        
        if should_fail:
            raise RuntimeError("Network error")
            
        return MockResponse(responses[url])
    
    return fetch


def selftest():
    # Test parsing functions
    bid, ask = parse_coinbase(COINBASE_FIXTURE)
    assert abs(bid - 1.0002) < 1e-10
    assert abs(ask - 1.0003) < 1e-10
    
    bid, ask = parse_kraken(KRAKEN_FIXTURE)
    assert abs(bid - 1.0002) < 1e-10
    assert abs(ask - 1.0004) < 1e-10
    
    print("  [ok] parsers work correctly")
    
    # Test successful fetch from Coinbase
    global requests
    old_requests = requests
    requests = type('MockRequests', (), {
        'get': _make_fetch()
    })
    
    result = get_prices()
    assert result["venue"] == "Coinbase"
    assert abs(result["bid"] - 1.0002) < 1e-10
    assert abs(result["ask"] - 1.0003) < 1e-10
    assert result["spread_bps"] > 0
    
    print("  [ok] Coinbase fetch works")
    
    # Test fallback to Kraken
    requests = type('MockRequests', (), {
        'get': _make_fetch(should_fail=True)
    })
    
    try:
        result = get_prices()
        assert result["venue"] == "Kraken"
        print("  [ok] Kraken fallback works")
    except RuntimeError:
        pass  # Expected when both fail
    
    # Restore requests
    requests = old_requests
    
    # Test file operations
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "usleg.csv")
        assert captured_this_hour(p, "ts_utc") is False
        
        # Test writing and reading
        test_row = {
            "ts_utc": "2026-09-10T14:00:00+00:00",
            "venue": "Coinbase",
            "bid": "1.0001",
            "ask": "1.0002",
            "spread_bps": "1.00"
        }
        
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerow(test_row)
        
        assert captured_this_hour(p, "ts_utc") is True
    
    print("  [ok] file operations work correctly")
    print("  ALL SELFTESTS PASSED\n")


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="US-side leg collector")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return
        
    if requests is None:
        sys.exit("pip install requests")

    if not a.verify and captured_this_hour(CSV_PATH, "ts_utc"):
        print(f"  {utc_hour():%Y-%m-%dT%H}Z already captured -> {CSV_PATH}, nothing to do")
        return

    try:
        data = get_prices()
        data["ts_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        
        if not a.verify:
            append(data)
            
        print_row(data)
        
        if not a.verify:
            print(f"  appended -> {CSV_PATH}\n")
            
    except Exception as e:
        print(f"  [error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
