#!/usr/bin/env python3
"""corridor.html's 24h/7d/30d/all-time history chart, as one small JSON.

The mockup (docs/mockups/route-breakdown.html) draws a bar chart of
stablecoin cost vs the cheapest app's cost, with four range buttons that
regroup the same points into coarser buckets (hourly for 24h, 6-hourly for
7 days, daily for 30 days and all-time). This script is the data side of
that: one hourly point per corridor+amount, {ts, stablecoin_cost_pct,
cheapest_app_cost_pct}, read straight from data/samples.csv. The page
buckets further into 6h/1d bars client-side (same idea as
tools/emit_coverage.py's gap detection: compute once here, let the page
regroup cheaply instead of re-reading samples.csv for every click).

Per DESIGN.md ("Numbers are computed from data/, never typed"): both series
come from real rows, never a typed example.

  stablecoin_cost_pct   = median(cost_bps_taker) / 100 for that hour's rows
                          -- the market-order, all-in cost, same field
                          corridor.html's own numCard() uzes for "Stablecoin,
                          market order".
  cheapest_app_cost_pct = median(baseline_cost_bps) / 100 for that hour's
                          rows -- the winner of the Wise comparison feed at
                          THAT hour. This is deliberately not cheapestApp()'s
                          richer "direct quote or comparison feed, whichever
                          is cheaper" logic: that logic only has an opinion
                          about the CURRENT hour (providers_latest.json has
                          no history of its own), so for every past hour the
                          comparison feed's own figure is the only real
                          number there is. corridor.html's existing
                          drawHistory() line chart already uses this same
                          field for the same reason -- this script keeps that
                          precedent rather than inventing a second one.

One row per corridor+size that was actually sampled; a size never sampled
for a corridor is simply absent, same convention as corridor.html's own
bySize/histBySize.

Rows are written as compact 4-tuples [hour, stablecoin_cost_pct,
cheapest_app_cost_pct, n] rather than objects with repeated field names --
this is the difference between a ~1.7MB and a ~450KB file at this row
count, and the page names the fields itself when it reads the array back
(same tradeoff data/samples.csv's own callers make with a header row).

Stdlib only. No wall clock in the output -- "generated" is the newest
sample's own timestamp.

Usage: python3 tools/emit_corridor_history.py
"""

import csv
import json
import os
import statistics as st

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SAMPLES = os.path.join(DATA, "samples.csv")
OUT = os.path.join(DATA, "corridor_history.json")

# Same threshold corridor.html's own drawHistory() and tools/emit_coverage.py
# use to decide a gap is real rather than normal collection jitter -- carried
# here so the range chart can break its line/bars the same way instead of a
# third, silently-different threshold.
GAP_THRESHOLD_HOURS = 3


def build():
    if not os.path.exists(SAMPLES):
        return None

    # buckets[corridor][size][hour_key] -> {"s": [...], "a": [...]}
    buckets = {}
    newest = ""
    with open(SAMPLES, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("source_ok") != "True":
                continue
            ts = row.get("ts") or ""
            if not ts:
                continue
            if ts > newest:
                newest = ts
            corridor = (row.get("corridor") or "").strip()
            size = (row.get("notional_src") or "").strip()
            if not corridor or not size:
                continue
            try:
                s_val = float(row["cost_bps_taker"]) / 100.0
                a_val = float(row["baseline_cost_bps"]) / 100.0
            except (KeyError, ValueError):
                continue
            hour_key = ts[:13]  # "YYYY-MM-DDTHH"
            c_bucket = buckets.setdefault(corridor, {})
            s_bucket = c_bucket.setdefault(size, {})
            hb = s_bucket.setdefault(hour_key, {"s": [], "a": []})
            hb["s"].append(s_val)
            hb["a"].append(a_val)

    corridors_out = {}
    for corridor, sizes in buckets.items():
        sizes_out = {}
        for size, hours in sizes.items():
            rows = []
            for hour_key in sorted(hours):
                hb = hours[hour_key]
                rows.append([
                    hour_key,
                    round(st.median(hb["s"]), 4),
                    round(st.median(hb["a"]), 4),
                    len(hb["s"]),
                ])
            sizes_out[size] = rows
        corridors_out[corridor] = {"sizes": sizes_out}

    return {
        "generated": newest,
        "gap_threshold_hours": GAP_THRESHOLD_HOURS,
        "corridors": corridors_out,
    }


def main():
    doc = build()
    if doc is None:
        print("no data/samples.csv -- nothing to emit")
        return
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    n_corridors = len(doc["corridors"])
    n_rows = sum(len(rows) for c in doc["corridors"].values()
                 for rows in c["sizes"].values())
    print(f"wrote {OUT}: {n_corridors} corridors, {n_rows} hourly rows total")


if __name__ == "__main__":
    main()
