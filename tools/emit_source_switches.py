#!/usr/bin/env python3
"""data/source_switches.csv: every hour a country's published number changed the KIND of source it came from.

Header (frozen): hour_utc,ccy,old_class,new_class,old_premium_pct,new_premium_pct,backfilled
  hour_utc          the first hour published from the new kind of source
  old_class         the source class of the country's previous priced hour
  new_class         this hour's source class (order_book_*, broker_*, p2p_buy_median or p2p_fallback)
  old_premium_pct   what the previous priced hour published
  new_premium_pct   what this hour published
  backfilled        true for rows built in one pass from the stored history when this file was created (9 Oct 2026);
                    false for rows written hour by hour afterwards

Read from data/index_hourly.csv, which holds the number each country published each hour. Nothing is recomputed.
A "previous priced hour" is the country's previous row, even if some hours lie between (a country with no price in an
hour has no row). Append only: a (ccy, hour) already here is never rewritten.

Usage: python3 tools/emit_source_switches.py            append switches found since the last run
       python3 tools/emit_source_switches.py --backfill  the first fill, rows marked backfilled=true
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(HERE, "data", "index_hourly.csv")
OUT = os.path.join(HERE, "data", "source_switches.csv")
HEADER = ["hour_utc", "ccy", "old_class", "new_class", "old_premium_pct", "new_premium_pct", "backfilled"]


def find_switches(rows):
    """rows: dicts from index_hourly.csv. Yields one switch per class change within a country, oldest first."""
    by = {}
    for r in rows:
        by.setdefault(r["ccy"], []).append(r)
    out = []
    for ccy, rs in by.items():
        rs.sort(key=lambda r: r["hour_utc"])
        for a, b in zip(rs, rs[1:]):
            if a["source_class"] != b["source_class"]:
                out.append([b["hour_utc"], ccy, a["source_class"], b["source_class"], a["index_pct"], b["index_pct"]])
    out.sort(key=lambda r: (r[0], r[1]))
    return out


def main():
    with open(IN, newline="") as f:
        switches = find_switches(list(csv.DictReader(f)))
    have = set()
    if os.path.exists(OUT):
        with open(OUT, newline="") as f:
            have = {(r["ccy"], r["hour_utc"]) for r in csv.DictReader(f)}
    first = not os.path.exists(OUT)
    flag = "true" if ("--backfill" in sys.argv or first) else "false"
    fresh = [s + [flag] for s in switches if (s[1], s[0]) not in have]
    if fresh or first:
        with open(OUT, "a", newline="") as f:
            w = csv.writer(f)
            if first:
                w.writerow(HEADER)
            w.writerows(fresh)
    print(f"  source_switches.csv: {len(fresh)} rows appended" + (" (backfilled)" if flag == "true" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
