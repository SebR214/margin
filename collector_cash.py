#!/usr/bin/env python3
"""Every money-changer tracker in collectors/cash_configs/, once an hour (SEB-422, lever 1, step 3). No model, no key.

Runs collectors/template_tracker.py for each config and appends one row per tracker to the daily table cash_rates (tools/daily_csv.py).
The rows are written before anything is printed. A tracker that fails is a row with source_ok false and the reason. Exits non-zero when no
tracker was read. Nothing reads the table yet: a new source starts in quarantine (data/source_registry.json).

Usage:  python3 collector_cash.py             # one pass
        python3 collector_cash.py --selftest   # parsers on fixtures, no network, writes nothing
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collectors import template_tracker as tt  # noqa: E402
import daily_csv  # noqa: E402


def main(argv):
    if "--selftest" in argv:
        return tt.selftest()
    cfgs = tt.load_all()
    if not cfgs:
        print("collector_cash: no configs in collectors/cash_configs/", file=sys.stderr)
        return 1
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for c in cfgs:
        try:
            rows.append(tt.row(ts, c, tt.fetch(c)))
        except Exception as e:
            rows.append(tt.row(ts, c, None, "%s:%s" % (type(e).__name__, e)))
    daily_csv.append(tt.NAME, tt.FIELDS, rows)                      # written before anything is printed
    ok = sum(1 for r in rows if r[7])
    print("collector_cash: %d of %d trackers read" % (ok, len(rows)))
    for r in rows:
        if not r[7]:
            print("  %s: %s" % (r[1], r[8]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
