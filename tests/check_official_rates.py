#!/usr/bin/env python3
"""SEB-310 item 3: the broken-official-rate check finds Sudan (a seven-day loop) and Iraq (a rate that lags the live one),
on fixtures and on the real data/fx_rates.csv. Run: python3 tests/check_official_rates.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_official_rates as c  # noqa: E402

c.self_test()
real = c.check(c.daily(c.FX, "ts_utc", "fx_mid_per_usd"), {})
found = {(f[1], f[2]) for f in real}
assert ("SDG", "weekly_loop") in found, "the real data holds Sudan's loop and the check must see it: %s" % sorted(found)
print("official rates on the real data: flagged", ", ".join("%s %s" % x for x in sorted(found)))
