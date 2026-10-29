"""Read the public Quidax usdtngn ticker with no key, write data/quidax_ngn.csv.
Not read by anything. The new source starts in quarantine, same as the other
first-venue collectors (SEB-301, BACKLOG 17, BACKLOG 22).
"""
import argparse
import csv
import os
import sys
import tempfile

try:
    import requests
except ImportError:
    requests = None

from collector_venue_common import now_ts, num, UA, TIMEOUT

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "quidax_ngn.csv")
URL = "https://www.quidax.com/api/v1/markets/tickers/usdtngn"
FIELDS = ["ts_utc", "bid", "ask", "last"]


def parse_ticker(payload, ts):
    """Pure function. Returns a row dict, or None."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None
    ticker = data.get("ticker") or {}
    if not isinstance(ticker, dict):
        return None
    
    bid = num(ticker.get("buy"))
    ask = num(ticker.get("sell"))
    last = num(ticker.get("last"))
    
    if bid is None or ask is None:
        return None
    if bid > ask:
        return None
    
    return {"ts_utc": ts, "bid": bid, "ask": ask, "last": "" if last is None else last}


def append_row(row, path=OUT):
    """Append one row to the CSV file, writing the header if needed."""
    if row is None:
        return False
    
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if write_header:
            w.writeheader()
        w.writerow(row)
    
    return True


def collect(payload, path=OUT, ts=None):
    """Parse payload and append the result."""
    return append_row(parse_ticker(payload, ts or now_ts()), path)


def fetch():
    """Fetch the Quidax ticker."""
    r = requests.get(URL, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def selftest():
    """Test the parser with valid and invalid payloads."""
    # Valid payload
    payload = {"status": "success", "data": {"ticker": {"buy": "1500", "sell": "1510", "last": "1505"}}}
    row = parse_ticker(payload, "t")
    assert row is not None and row["bid"] == 1500.0 and row["ask"] == 1510.0, row
    
    # Missing sell key
    payload2 = {"status": "success", "data": {"ticker": {"buy": "1500", "last": "1505"}}}
    assert parse_ticker(payload2, "t") is None
    
    # Test with temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = os.path.join(tmpdir, "test.csv")
        result = collect(payload2, path=tmppath, ts="t")
        assert result is False
        assert not os.path.exists(tmppath) or os.path.getsize(tmppath) == 0
    
    # Test edge cases
    assert parse_ticker({}, "t") is None
    assert parse_ticker(None, "t") is None
    
    print("selftest OK")


def main():
    """Main entry point."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    
    if args.selftest:
        selftest()
        return 0
    
    if requests is None:
        sys.exit("pip install requests")
    
    try:
        payload = fetch()
    except Exception as e:
        print(f"quidax_ngn: pull failed: {type(e).__name__}:{e}")
        return 1
    
    if collect(payload):
        print("quidax_ngn: 1 row written")
        return 0
    else:
        print("quidax_ngn: ticker had no usable bid and ask, no row written")
        return 1


if __name__ == "__main__":
    sys.exit(main())
