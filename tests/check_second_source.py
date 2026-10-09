#!/usr/bin/env python3
"""The v1.2 rule for a second source (SEB-256, SEB-254): ignored when its price has stood still for 24 hours."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import emit_countries as ec  # noqa: E402

H = dt.datetime(2026, 10, 9, 5, tzinfo=dt.timezone.utc)
flat = {H - dt.timedelta(hours=k): 4.1 for k in range(24)}
assert ec.unchanged_24h(flat, H), "24 identical hourly readings is standing still"
moving = dict(flat)
moving[H - dt.timedelta(hours=7)] = 4.2
assert not ec.unchanged_24h(moving, H), "one different reading means the book moved"
short = {H - dt.timedelta(hours=k): 4.1 for k in range(10)}
assert not ec.unchanged_24h(short, H), "a source with under 20 readings in the window is not judged"
gappy = {H - dt.timedelta(hours=k): 4.1 for k in range(24) if k % 2 == 0}
assert not ec.unchanged_24h(gappy, H), "12 readings are too few to call it stale"
nearly = {H - dt.timedelta(hours=k): 4.1 for k in range(24) if k not in (3, 9, 15)}
assert ec.unchanged_24h(nearly, H), "21 identical readings with a few hours missing is still stale"
assert ec.SECOND_BOARD_MAX_GAP == 0.03
print("second source rule ok")
