#!/usr/bin/env python3
"""What picking the wrong stablecoin path costs, per route (SEB-263, first output: numbers, no page). Stored files only, no model.

For SGD to PHP, AUD to PHP and NZD to PHP at 5,000, in every hour in which BOTH stored paths were priced (the base route in
data/samples.csv and its one variant in data/corridor_variants.csv, USDC over Arbitrum One), it writes the two costs side by side to
data/path_spread_hours.csv and prints one table per route:

  the median spread (the dearer path's all-in cost minus the cheaper's) and the widest, with its hour
  how many paths were priced, and how many hours each had
  which path was cheaper how often, and how often the cheaper one changed from one hour to the next
  which step carries the spread: the median absolute difference per step (deposit, buying, on-chain move, selling, withdrawal) over
  the hours where both paths' steps were stored (the variant's steps are stored from 11 Oct)
  the cost of not re-checking: for each full week, the path with the lower median cost is "kept" for the week after; the cost is that
  kept path's cost minus the cheaper of the two in each hour of the next week, averaged over the hours

USD to Mexico has one stored path, so it has no spread to measure. USD to Nigeria, India and Singapore to India are left out (SEB-263).
An hour counts only if both paths' rows are source_ok true and every figure is there; the hours left out are counted per route.

Usage:  python3 tools/path_spread.py
"""
import csv
import datetime as dt
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "path_spread_hours.csv")
ROUTES = ["SGD->PHP", "AUD->PHP", "NZD->PHP"]
AMOUNT = 5000
SYM = {"SGD": "S$", "AUD": "A$", "NZD": "NZ$"}
STEPS = ["deposit", "buy", "move", "sell", "withdrawal"]
BASE = "USDT over Tron"
VAR = "USDC over Arbitrum One"


def hour(ts):
    return ts[:13] + ":00:00Z"


def rows(name):
    with open(os.path.join(DATA, name), newline="") as f:
        return list(csv.DictReader(f))


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load():
    base, var = {}, {}
    for r in rows("samples.csv"):
        if r["corridor"] in ROUTES and f(r["notional_src"]) == AMOUNT and r["source_ok"] == "True" and f(r["cost_bps_taker"]) is not None:
            base[(r["corridor"], hour(r["ts"]))] = f(r["cost_bps_taker"])
    for r in rows("corridor_variants.csv"):
        if r["corridor"] in ROUTES and f(r["notional_src"]) == AMOUNT and r["source_ok"] == "True" and f(r["cost_bps_taker"]) is not None:
            var[(r["corridor"], hour(r["ts"]))] = f(r["cost_bps_taker"])
    legs_b, legs_v = {}, {}
    wf = {(r["corridor"], hour(r["ts"])): r for r in rows("corridor_waterfall.csv") if r["corridor"] in ROUTES and f(r["notional_src"]) == AMOUNT}
    rw = {(r["corridor"], hour(r["ts"])): r for r in rows("ramp_waterfall.csv") if r["corridor"] in ROUTES and f(r["notional_src"]) == AMOUNT}
    for k, a in wf.items():
        b = rw.get(k)
        vals = [f(b["wf_deposit_bps"]) if b else None, f(a["wf_buy_bps"]), f(a["wf_move_bps"]), f(a["wf_sell_bps"]), f(b["wf_withdrawal_bps"]) if b else None]
        if None not in vals:
            legs_b[k] = dict(zip(STEPS, vals))
    for r in rows("corridor_variant_legs.csv"):
        if r["corridor"] in ROUTES and f(r["notional_src"]) == AMOUNT:
            vals = [f(r["wf_" + s + "_bps"]) for s in STEPS]
            if None not in vals:
                legs_v[(r["corridor"], hour(r["ts"]))] = dict(zip(STEPS, vals))
    return base, var, legs_b, legs_v


def analyse(route, base, var, legs_b, legs_v):
    hrs = sorted(h for (c, h) in base if c == route and (route, h) in var)
    table = [(h, base[(route, h)], var[(route, h)]) for h in hrs]
    out = {"route": route, "hours_both": len(hrs), "hours_base": sum(1 for (c, _) in base if c == route),
           "hours_variant": sum(1 for (c, _) in var if c == route)}
    if not table:
        return out, table
    spreads = [abs(b - v) for _, b, v in table]
    out["median_spread_bps"] = st.median(spreads)
    w = max(range(len(table)), key=lambda i: spreads[i])
    out["widest_spread_bps"], out["widest_hour"] = spreads[w], table[w][0]
    cheaper = [BASE if b <= v else VAR for _, b, v in table]
    out["cheaper_base_hours"] = cheaper.count(BASE)
    out["cheaper_variant_hours"] = cheaper.count(VAR)
    out["changes"] = sum(1 for a, b in zip(cheaper, cheaper[1:]) if a != b)
    both = [h for h in hrs if (route, h) in legs_b and (route, h) in legs_v]
    out["hours_with_steps"] = len(both)
    if both:
        out["step_diff"] = {s: st.median(abs(legs_b[(route, h)][s] - legs_v[(route, h)][s]) for h in both) for s in STEPS}
    # the cost of not re-checking
    byweek = {}
    for h, b, v in table:
        d = dt.datetime.strptime(h, "%Y-%m-%dT%H:00:00Z")
        byweek.setdefault(d.isocalendar()[:2], []).append((b, v))
    weeks = sorted(byweek)
    kept, n_weeks = [], 0
    for w0, w1 in zip(weeks, weeks[1:]):
        if len(byweek[w0]) < 100 or len(byweek[w1]) < 100:
            continue                                                                   # a week needs 100 hours of both paths to be judged
        pick = 0 if st.median(b for b, _ in byweek[w0]) <= st.median(v for _, v in byweek[w0]) else 1
        kept.extend(x[pick] - min(x) for x in byweek[w1])
        n_weeks += 1
    out["kept_weeks"] = n_weeks
    out["kept_cost_bps"] = (sum(kept) / len(kept)) if kept else None
    return out, table


def main():
    base, var, legs_b, legs_v = load()
    allrows = []
    for route in ROUTES:
        a, table = analyse(route, base, var, legs_b, legs_v)
        sym = SYM[route.split("->")[0]]
        print("\n%s at %s%s,000" % (route, sym, AMOUNT // 1000))
        if not table:
            print("  no hour with both paths priced")
            continue
        m = a["median_spread_bps"]
        print("  paths priced: 2 (%s, %s); hours priced: %d and %d, both %d" % (BASE, VAR, a["hours_base"], a["hours_variant"], a["hours_both"]))
        print("  median spread: %s%.0f (%.2f%% of the amount), %.1f bps" % (sym, m * AMOUNT / 1e4, m / 100, m))
        print("  widest spread: %s%.0f (%.2f%%) at %s" % (sym, a["widest_spread_bps"] * AMOUNT / 1e4, a["widest_spread_bps"] / 100, a["widest_hour"]))
        print("  cheaper: %s %d hours, %s %d hours; the cheaper path changed %d times" % (BASE, a["cheaper_base_hours"], VAR, a["cheaper_variant_hours"], a["changes"]))
        if a.get("step_diff"):
            top = max(a["step_diff"], key=a["step_diff"].get)
            print("  step that carries most of it (median absolute difference, bps, over %d hours with both paths' steps): %s; all: %s" % (
                a["hours_with_steps"], top, ", ".join("%s %.1f" % (s, a["step_diff"][s]) for s in STEPS)))
        if a["kept_cost_bps"] is not None:
            k = a["kept_cost_bps"]
            print("  cost of not re-checking (last week's cheaper path kept for %d weeks): %s%.1f an hour on %s%d, %.2f bps" % (a["kept_weeks"], sym, k * AMOUNT / 1e4, sym, AMOUNT, k))
        else:
            print("  cost of not re-checking: fewer than two full weeks with 100 hours of both paths")
        for h, b, v in table:
            allrows.append([route, h, b, v, BASE if b <= v else VAR, round(abs(b - v), 2)])
    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["route", "hour_utc", "base_cost_bps_usdt_tron", "variant_cost_bps_usdc_arbitrum", "cheaper", "spread_bps"])
        w.writerows(allrows)
    print("\nwrote %s (%d hours)" % (os.path.relpath(OUT, HERE), len(allrows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
