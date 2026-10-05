#!/usr/bin/env python3
"""data/heatmap_daily.json: every currency by every day since the first reading.

Each cell is that day's median gap between the real dollar price and the
official rate, in percent: (price to buy a dollar / official rate - 1) * 100.

Where the published country history (data/countries/<CCY>.json "history", the
daily values the site already shows) has the day, the cell IS that published
value. For earlier days of a currency priced from order books, the cell is the
median of that day's raw order-book rows in data/basis.csv, with the same buy
price and the same formula tools/emit_countries.py uses. A day with no reading
is null: never filled, never carried over. The `raw` list says which cells came
from raw rows, so a reader can tell them apart.

Reads stored files only. Idempotent: no wall clock, same inputs, same bytes.
Stdlib only.  Usage: python3 tools/emit_heatmap.py
"""

import csv
import datetime as dt
import json
import os
import statistics

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "heatmap_daily.json")


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def main():
    idx = json.load(open(os.path.join(DATA, "index_latest.json")))
    countries = {c["ccy"]: c for c in idx["countries"]}
    for w in idx["withheld"]:
        countries.setdefault(w["ccy"], w)
    # a currency the index lists as unverified is still one we cover: a row with whatever readings it has
    for u in idx.get("unverified") or []:
        ccy = u if isinstance(u, str) else u.get("ccy")
        if ccy and ccy not in countries:
            fp = os.path.join(DATA, "countries", ccy + ".json")
            name = json.load(open(fp)).get("country", ccy) if os.path.exists(fp) else ccy
            countries[ccy] = {"ccy": ccy, "country": name}
    # raw order-book rows, per currency and day
    raw = {}
    first_ts = None
    with open(os.path.join(DATA, "basis.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("source_ok") or "").strip().lower() != "true":
                continue
            v = r.get("venue") or ""
            if v.startswith("CriptoYa ("):
                continue  # aggregate rows are not a venue
            price = num(r.get("usdt_ask")) or num(r.get("usdt_mid"))
            fx = num(r.get("fx_mid_per_usd"))
            if not price or not fx:
                continue
            day = r["ts_utc"][:10]
            raw.setdefault(r["ccy"], {}).setdefault(day, []).append(round((price / fx - 1) * 100, 4))
            first_ts = day if first_ts is None or day < first_ts else first_ts
    published = {}
    last_day = None
    for ccy in countries:
        p = os.path.join(DATA, "countries", ccy + ".json")
        if os.path.exists(p):
            d = json.load(open(p))
            published[ccy] = {h["date"]: (h["index_pct"], h.get("n")) for h in d.get("history", []) if h.get("index_pct") is not None}
            for day in published[ccy]:
                last_day = day if last_day is None or day > last_day else last_day
    # the collector's first reading is the start of the record; older dates in a country
    # file (if any) are not part of it
    start = first_ts
    for ccy in published:
        published[ccy] = {k: v for k, v in published[ccy].items() if k >= start}
    days = []
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(last_day)
    while d0 <= d1:
        days.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    out = []
    for ccy in sorted(countries, key=lambda c: countries[c].get("country", c)):
        c = countries[ccy]
        cells, n, rawmark = [], [], []
        for i, day in enumerate(days):
            if day in published.get(ccy, {}):
                v, k = published[ccy][day]
                cells.append(v)
                n.append(k)
            elif day in raw.get(ccy, {}):
                vals = raw[ccy][day]
                cells.append(round(statistics.median(vals), 4))
                n.append(len(vals))
                rawmark.append(i)
            else:
                cells.append(None)
                n.append(None)
        out.append({"ccy": ccy, "country": c.get("country", ccy), "class": c.get("denominator_class"),
                    "ranked": c.get("denominator_class") != "unmaintained", "cells": cells, "n": n, "raw": rawmark})
    doc = {"as_of_utc": idx.get("as_of_utc"), "first_day": days[0], "last_day": days[-1], "days": days,
           "source_files": ["data/countries/<CCY>.json", "data/basis.csv"], "currencies": out}
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    filled = sum(1 for r in out for v in r["cells"] if v is not None)
    print("heatmap: %d currencies x %d days (%s to %s), %d cells with a reading of %d" % (
        len(out), len(days), days[0], days[-1], filled, len(out) * len(days)))


if __name__ == "__main__":
    main()
