#!/usr/bin/env python3
"""data/index_hourly.csv: the number each country published, one row per country and hour.

Until now only the newest published number was stored (data/index_latest.json); a past hour's published number
existed only inside the hourly data commits. The exchange-versus-people finding and the source-switch log both
need it ("never recompute a past hour's published number"), so this file keeps it.

Header (frozen): hour_utc,ccy,source_class,index_pct,n_sources
  hour_utc      the UTC hour the published number is for (index_latest.json: countries[].hour_utc)
  source_class  order_book_median, order_book_single, broker_median, broker_single, p2p_buy_median or p2p_fallback
  index_pct     the published premium over the official rate, as published
  n_sources     as published (buy-side ads for person-to-person countries, venues for the others)

Append only. A (ccy, hour) already in the file is never rewritten. Countries with no price that hour have no row.
Every hour: python3 tools/emit_index_hourly.py
Once, to fill the past from the stored snapshots in git history: python3 tools/emit_index_hourly.py --backfill
(each hourly data commit holds the index_latest.json of its hour; the last snapshot that carries a given hour wins,
because that is the number the site showed for it).
"""

import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, "data", "index_hourly.csv")
HEADER = ["hour_utc", "ccy", "source_class", "index_pct", "n_sources"]


def hour_key(s):
    return str(s or "")[:13]            # 2026-10-09T05


def rows_from_snapshot(doc):
    out = []
    for c in doc.get("countries") or []:
        if c.get("index_pct") is None or not c.get("source_class") or not c.get("hour_utc") or not c.get("ccy"):
            continue
        out.append([hour_key(c["hour_utc"]) + ":00:00+00:00", c["ccy"], c["source_class"], c["index_pct"],
                    "" if c.get("n_sources") is None else c["n_sources"]])
    return out


def existing():
    if not os.path.exists(PATH):
        return set()
    with open(PATH, newline="") as f:
        return {(r["ccy"], hour_key(r["hour_utc"])) for r in csv.DictReader(f)}


def append(rows):
    have = existing()
    fresh = [r for r in rows if (r[1], hour_key(r[0])) not in have]
    new_file = not os.path.exists(PATH)
    if fresh or new_file:
        with open(PATH, "a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(HEADER)
            w.writerows(fresh)
    return len(fresh)


def backfill():
    """Walk every stored snapshot oldest first; the newest snapshot that carries an hour decides it."""
    shas = subprocess.check_output(["git", "log", "--reverse", "--format=%H", "--", "data/index_latest.json"],
                                   cwd=HERE, text=True).split()
    by = {}
    for sha in shas:
        try:
            doc = json.loads(subprocess.check_output(["git", "show", sha + ":data/index_latest.json"], cwd=HERE, text=True))
        except (subprocess.CalledProcessError, ValueError):
            continue
        for r in rows_from_snapshot(doc):
            by[(r[1], hour_key(r[0]))] = r
    rows = sorted(by.values(), key=lambda r: (r[0], r[1]))
    return append(rows), len(shas)


def main():
    if "--backfill" in sys.argv:
        n, s = backfill()
        print(f"  index_hourly.csv: backfilled {n} rows from {s} stored snapshots")
        return 0
    with open(os.path.join(HERE, "data", "index_latest.json")) as f:
        n = append(rows_from_snapshot(json.load(f)))
    print(f"  index_hourly.csv: {n} rows appended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
