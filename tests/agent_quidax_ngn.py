#!/usr/bin/env python3
import os
import sys

# Add repo root to path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo_root)

import collector_quidax_ngn as q


def main():
    # Test normal case
    ok = {"data": {"ticker": {"buy": "1500", "sell": "1510", "last": "1505"}}}
    row = q.parse_ticker(ok, "t")
    assert row["bid"] == 1500
    assert row["ask"] == 1510
    
    # Test missing sell field
    result = q.parse_ticker({"data": {"ticker": {"buy": "1500", "last": "1505"}}}, "t")
    assert result is None
    
    # Run selftest
    q.selftest()
    
    print("agent_quidax_ngn OK")


if __name__ == "__main__":
    main()
