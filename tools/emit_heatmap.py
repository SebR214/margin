#!/usr/bin/env python3
"""The heatmap data: 60 currencies, one cell per day since collection began.

SEB-240 step 0. Reuses emit_countries.daily_history() -- the same function
that already feeds each country page's history -- so this never computes a
second, possibly-drifting figure for the same day. The only thing added here
is the filter: daily_history() also folds in the old daily backfill layer
(every row before 2026-08-10) so country pages can show a dashed early
segment; emit_countries.py is that layer's one allowed reader outside its own
writer, per tools/check_history_isolation.py. The heatmap is the live,
observed series only, so backfill rows and anything before 2026-08-10, when
live collection began, are dropped here. Nothing here is a second index; it
is the same numbers with the backfill left out.

Stdlib only. Nothing is interpolated: a currency with no live reading on a
day gets no cell value for that day, not a filled one.

Usage: python3 tools/emit_heatmap.py
"""

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import emit_countries as ec  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "heatmap.json")

START_DATE = dt.date(2026, 8, 10)  # the day live collection began (basis.csv's first row)


def build():
    hist = ec.daily_history()
    today = dt.date.today()
    dates = [(START_DATE + dt.timedelta(days=i)).isoformat()
             for i in range((today - START_DATE).days + 1)]

    currencies = []
    for ccy in sorted(hist.keys() | ec.COUNTRY.keys()):
        by_date = {}
        for point in hist.get(ccy, []):
            if point["source"] == "daily_backfill_mid":
                continue  # the backfill layer; never in the observed series
            d = point["date"]
            if d < START_DATE.isoformat():
                continue
            by_date[d] = {"index_pct": point["index_pct"], "n": point["n"]}
        cells = [by_date.get(d) for d in dates]
        currencies.append({
            "ccy": ccy,
            "country": ec.COUNTRY.get(ccy, ccy),
            "unranked": ccy in ec.UNMAINTAINED,
            "cells": cells,
        })

    doc = {
        "start_date": dates[0],
        "end_date": dates[-1],
        "dates": dates,
        "currencies": currencies,
        "sources": ["data/basis.csv", "data/p2p_basis.csv"],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    return doc


def main():
    doc = build()
    n_cells = sum(sum(1 for c in cur["cells"] if c) for cur in doc["currencies"])
    print(f"wrote data/heatmap.json  ({len(doc['currencies'])} currencies, "
          f"{doc['start_date']}..{doc['end_date']}, {n_cells} cells with a value)")


if __name__ == "__main__":
    main()
