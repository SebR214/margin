#!/usr/bin/env python3
"""Second Nigeria source, in quarantine. Nothing reads this file.

Reads the public Quidax ticker with no key. A failed or incomplete pull writes no row.
"""
import argparse
import csv
import os
import sys

from collector_venue_common import now_ts, num, UA, TIMEOUT

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "quidax_ngn.csv")
FIELDS = ["ts_utc", "bid", "ask", "last"]
URL = "https://www.quidax.com/api/v1/markets/tickers/usdtngn"


def parse_ticker(payload, ts):
    """Pure function that returns a dict {ts_utc, bid, ask, last} or None. Never raises."""
    try:
        if isinstance(payload.get("data", {}).get("ticker"), dict):
            t = payload["data"]["ticker"]
        elif isinstance(payload.get("ticker"), dict):
            t = payload["ticker"]
        elif isinstance(payload, dict):
            t = payload
        else:
            return None
        
        bid = num(t.get("buy"))
        ask = num(t.get("sell"))
        
        if bid is None or ask is None:
            return None
            
        if bid >= ask:
            return None
            
        last = num(t.get("last"))
        if last is None:
            last = ""
            
        return {"ts_utc": ts, "bid": bid, "ask": ask, "last": last}
    except:
        return None


def fetch():
    import requests
    r = requests.get(URL, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def already_this_hour(path, ts):
    """Return True if the file exists and its last non-empty data line starts with ts[:13]."""
    if not os.path.exists(path):
        return False
    
    try:
        with open(path, "r", newline="") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            # Skip header line
            data_lines = lines[1:] if len(lines) > 1 else []
            if not data_lines:
                return False
            last_line = data_lines[-1]
            return last_line.startswith(ts[:13])
    except (IOError, IndexError):
        return False


def append(row, path=OUT):
    """Append one row to the CSV file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if write_header:
            w.writeheader()
        w.writerow(row)


def selftest():
    # Test normal case
    payload = {"data": {"ticker": {"buy": "1500", "sell": "1510", "last": "1505"}}}
    row = parse_ticker(payload, "t")
    assert row["bid"] == 1500.0, f"Expected bid 1500.0, got {row['bid']}"
    assert row["ask"] == 1510.0, f"Expected ask 1510.0, got {row['ask']}"
    assert row["last"] == 1505.0, f"Expected last 1505.0, got {row['last']}"
    
    # Test missing sell field
    result = parse_ticker({"data": {"ticker": {"buy": "1500", "last": "1505"}}}, "t")
    assert result is None, f"Expected None for missing sell field, got {result}"
    
    # Test garbage input
    assert parse_ticker(None, "t") is None
    assert parse_ticker({}, "t") is None
    assert parse_ticker("x", "t") is None
    
    # Test flat shape
    flat_payload = {"buy": "1500", "sell": "1510"}
    row2 = parse_ticker(flat_payload, "t")
    assert row2["bid"] == 1500.0
    assert row2["ask"] == 1510.0
    assert row2["last"] == ""
    
    # Test crossed book
    crossed = {"buy": "1510", "sell": "1500"}
    assert parse_ticker(crossed, "t") is None
    
    # Test file operations with temporary directory
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = os.path.join(tmpdir, "test.csv")
        test_row = {"ts_utc": "2023-01-01T12:00:00Z", "bid": 1500.0, "ask": 1510.0, "last": 1505.0}
        append(test_row, test_path)
        
        # Check file contents
        with open(test_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 row
        assert lines[0].strip() == "ts_utc,bid,ask,last"
        assert "2023-01-01T12:00:00Z" in lines[1]
        
        # Test already_this_hour
        assert already_this_hour(test_path, "2023-01-01T12:30:00Z") == True
        assert already_this_hour(test_path, "2023-01-01T13:00:00Z") == False
    
    print("  selftest OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    
    if args.selftest:
        selftest()
        return 0
    
    ts = now_ts()
    
    if already_this_hour(OUT, ts):
        print(f"quidax_ngn: already captured for {ts[:13]}")
        return 0
    
    try:
        payload = fetch()
        row = parse_ticker(payload, ts)
        if row is None:
            print("quidax_ngn: no usable ticker")
            return 1
    except Exception as e:
        print(f"quidax_ngn: {type(e).__name__}:{e}")
        return 1
    
    append(row)
    print(f"quidax_ngn: bid {row['bid']} ask {row['ask']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
