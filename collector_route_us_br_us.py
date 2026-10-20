#!/usr/bin/env python3
"""
US-BR route collector: Coinbase and Kraken dollar-stablecoin quotes.

This collector fetches the USD price of USDC from Coinbase and Kraken,
writing one row per venue to data/route_us_br_us.csv with UTC timestamp,
venue identifier, best bid, best ask, and mid price.
"""

import csv
import datetime as dt
import os
import sys

try:
    import requests
except ImportError:
    requests = None

# Import the HTTP helper from collector_stable_venues.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import collector_stable_venues as http_helper

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "route_us_br_us.csv")

# Venues to probe
VENUES = {
    "Coinbase": "https://api.exchange.coinbase.com/products/USDC-USD/book?level=1",
    "Kraken": "https://api.kraken.com/0/public/Ticker?pair=USDCUSD"
}

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki us-br-us-collector/1.0 (+https://margin.wiki)"}


def get_coinbase_quote(url):
    """Fetch Coinbase USDC-USD quote -> (bid, ask, mid) or (None, None, None)."""
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
        r.raise_for_status()
        d = r.json()
        asks = http_helper.collector.norm_levels(d.get("asks", []))
        bids = http_helper.collector.norm_levels(d.get("bids", []))
        if not asks or not bids:
            return None, None, None
        best_ask = asks[0][0]  # First ask (lowest)
        best_bid = bids[0][0]  # First bid (highest)
        mid = (best_bid + best_ask) / 2
        return best_bid, best_ask, mid
    except Exception:
        return None, None, None


def get_kraken_quote(url):
    """Fetch Kraken USDCUSD quote -> (bid, ask, mid) or (None, None, None)."""
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            return None, None, None
        pair_data = list(d.get("result", {}).values())
        if not pair_data:
            return None, None, None
        ticker = pair_data[0]
        best_ask = float(ticker["a"][0])  # Ask array: [price, whole_lot_volume, lot_volume]
        best_bid = float(ticker["b"][0])  # Bid array: [price, whole_lot_volume, lot_volume]
        mid = (best_bid + best_ask) / 2
        return best_bid, best_ask, mid
    except Exception:
        return None, None, None


def fetch_quotes():
    """Fetch quotes from all venues -> list of dicts."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for venue, url in VENUES.items():
        if venue == "Coinbase":
            bid, ask, mid = get_coinbase_quote(url)
        elif venue == "Kraken":
            bid, ask, mid = get_kraken_quote(url)
        else:
            continue
        if bid is not None and ask is not None and mid is not None:
            rows.append({
                "ts_utc": ts,
                "venue": venue,
                "best_bid": round(bid, 6),
                "best_ask": round(ask, 6),
                "mid": round(mid, 6)
            })
    return rows


def append(rows, path=OUT):
    """Append rows to CSV, creating it with header if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts_utc", "venue", "best_bid", "best_ask", "mid"])
        if new:
            w.writeheader()
        w.writerows(rows)
    return path


def main():
    if requests is None:
        sys.exit("pip install requests")
    rows = fetch_quotes()
    if rows:
        path = append(rows)
        print(f"appended {len(rows)} rows -> {path}")
    else:
        print("no quotes fetched")


if __name__ == "__main__":
    main()
