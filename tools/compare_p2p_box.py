#!/usr/bin/env python3
"""Daily comparison: the box collector against GitHub Actions (ROADMAP item 16, SEB-206).

Each UTC day, for each of its 24 hours, compare the on-the-hour box pass (the
first box pass inside that hour, the :02 slot) with the Actions pass for the
same hour (data/p2p_basis.csv, ~:05):

  same currencies priced     priced on one side and not the other
  same currencies withheld   (the other half of the same test, listed separately)
  same index values          (buy median / official rate - 1) * 100 within a tolerance

"Priced" means the same thing the published index means (METHODOLOGY v1.1):
at least 10 buy-side ads at roughly USD 500 and the buy median at or above the
sell median. The box's own ten-minute pass reads the whole first page with no
amount filter, so it is not comparable; instead the box runs the hourly
collector's own collect() once an hour (collector_p2p_box.hourly_basis_pass) and
this script compares THAT file, same query and same arithmetic, with Actions.

Missing hours are counted apart from mismatches: a day is CLEAN only when all
24 hours had both passes, nothing mismatched, and every priced-set and
withheld-set agreed. Any non-clean day resets the clean streak. The switch (item
16) needs 7 clean days in a row.

Reads the box's hourly Actions-equivalent pass (BOX_STATE_DIR/basis_actions_equiv.csv) and the repo's
data/ (the served checkout, fast-forwarded every five minutes). Writes, outside
every git checkout:
  BOX_STATE_DIR/compare_daily.csv          one append-only line per day compared
  BOX_STATE_DIR/compare_detail/<date>.csv  every hour x currency that disagreed
and prints the summary (the systemd unit appends it to a log).

Usage:
  python3 tools/compare_p2p_box.py                 # yesterday (UTC)
  python3 tools/compare_p2p_box.py --date 2026-10-04
  python3 tools/compare_p2p_box.py --date 2026-10-04 --dry-run
"""

import argparse
import csv
import datetime as dt
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
STATE = os.environ.get("BOX_STATE_DIR", "/var/lib/margin/p2p_box")

MIN_BUY_ADS = 10
INDEX_TOL = float(os.environ.get("COMPARE_INDEX_TOL", "0.5"))  # index points

DAILY_FIELDS = ["date", "hours_expected", "hours_both", "hours_missing_actions", "hours_missing_box",
                "ccy_hours_compared", "priced_both", "priced_only_actions", "priced_only_box",
                "withheld_both", "index_compared", "index_mismatch", "index_abs_diff_median",
                "index_abs_diff_max", "tolerance_points", "clean", "clean_streak", "computed_at"]
DETAIL_FIELDS = ["hour", "ccy", "kind", "actions_index", "box_index", "actions_priced", "box_priced"]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hour_key(ts):
    return ts[:13]


def actions_side(day):
    """{hour: {ccy: {priced, index}}} from the Actions layer for `day`."""
    basis = {}
    with open(os.path.join(DATA, "p2p_basis.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["ts_utc"][:10] == day and r.get("source") == "binance_p2p":
                basis.setdefault(hour_key(r["ts_utc"]), {})[r["ccy"]] = r
    sides = {}
    with open(os.path.join(DATA, "p2p_sides.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["ts_utc"][:10] == day:
                sides[(hour_key(r["ts_utc"]), r["ccy"])] = int(r["n_buy"] or 0)
    out = {}
    for h, rows in basis.items():
        for ccy, r in rows.items():
            ok = str(r["source_ok"]).strip().lower() == "true"
            buy, sell, fx = num(r["buy_median"]), num(r["sell_median"]), num(r["fx_mid_per_usd"])
            n_buy = sides.get((h, ccy))
            if n_buy is None:
                total = num(r["n_ads"]) or 0
                n_buy = MIN_BUY_ADS if total >= MIN_BUY_ADS * 2 else 0
            priced = bool(ok and buy is not None and n_buy >= MIN_BUY_ADS and (sell is None or buy >= sell))
            idx = (buy / fx - 1) * 100 if (buy is not None and fx) else None
            out.setdefault(h, {})[ccy] = {"priced": priced, "index": idx, "fx": fx}
    return out


def box_side(day, _fx_by_hour=None):
    """{hour: {ccy: {priced, index}}} from the box's hourly Actions-equivalent
    pass (collector_p2p.collect() run on the box, BOX_STATE_DIR/basis_actions_equiv.csv)."""
    path = os.path.join(STATE, "basis_actions_equiv.csv")
    if not os.path.exists(path):
        return {}, set()
    out, hours = {}, set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["ts_utc"][:10] != day:
                continue
            h = hour_key(r["ts_utc"])
            if h in out and r["ts_utc"][:16] != next(iter(out[h].values()))["ts"][:16]:
                continue  # one pass per hour: the first
            ok = str(r["source_ok"]).strip().lower() == "true"
            buy, sell, fx = num(r["buy_median"]), num(r["sell_median"]), num(r["fx_mid_per_usd"])
            n_buy = int(num(r["n_buy"]) or 0)
            priced = bool(ok and buy is not None and n_buy >= MIN_BUY_ADS and (sell is None or buy >= sell))
            idx = (buy / fx - 1) * 100 if (buy is not None and fx) else None
            out.setdefault(h, {})[r["ccy"]] = {"priced": priced, "index": idx, "ts": r["ts_utc"]}
            hours.add(h)
    return out, hours


def read_daily():
    p = os.path.join(STATE, "compare_daily.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def compare(day):
    act = actions_side(day)
    fx_by_hour = {h: {c: v["fx"] for c, v in rows.items()} for h, rows in act.items()}
    box, box_hours = box_side(day, fx_by_hour)
    hours = ["%sT%02d" % (day, i) for i in range(24)]
    detail, diffs = [], []
    c = dict(hours_expected=24, hours_both=0, hours_missing_actions=0, hours_missing_box=0, ccy_hours_compared=0,
             priced_both=0, priced_only_actions=0, priced_only_box=0, withheld_both=0, index_compared=0,
             index_mismatch=0)
    for h in hours:
        a, b = act.get(h), box.get(h)
        if not a:
            c["hours_missing_actions"] += 1
        if not b:
            c["hours_missing_box"] += 1
        if not a or not b:
            continue
        c["hours_both"] += 1
        for ccy in sorted(set(a) & set(b)):
            c["ccy_hours_compared"] += 1
            pa, pb = a[ccy]["priced"], b[ccy]["priced"]
            if pa and pb:
                c["priced_both"] += 1
                ia, ib = a[ccy]["index"], b[ccy]["index"]
                if ia is not None and ib is not None:
                    c["index_compared"] += 1
                    d = abs(ia - ib)
                    diffs.append(d)
                    if d > INDEX_TOL:
                        c["index_mismatch"] += 1
                        detail.append([h, ccy, "index", round(ia, 4), round(ib, 4), pa, pb])
            elif pa and not pb:
                c["priced_only_actions"] += 1
                detail.append([h, ccy, "priced_only_actions", a[ccy]["index"], b[ccy]["index"], pa, pb])
            elif pb and not pa:
                c["priced_only_box"] += 1
                detail.append([h, ccy, "priced_only_box", a[ccy]["index"], b[ccy]["index"], pa, pb])
            else:
                c["withheld_both"] += 1
    clean = (c["hours_both"] == 24 and c["priced_only_actions"] == 0 and c["priced_only_box"] == 0
             and c["index_mismatch"] == 0)
    c["index_abs_diff_median"] = round(statistics.median(diffs), 4) if diffs else ""
    c["index_abs_diff_max"] = round(max(diffs), 4) if diffs else ""
    c["tolerance_points"] = INDEX_TOL
    c["clean"] = clean
    return c, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    day = a.date or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    c, detail = compare(day)

    prior = [r for r in read_daily() if r["date"] < day]
    streak = 0
    for r in sorted(prior, key=lambda r: r["date"], reverse=True):
        if r["clean"] == "True":
            streak += 1
        else:
            break
    c["clean_streak"] = streak + 1 if c["clean"] else 0
    c["date"] = day
    c["computed_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    print("p2p box vs actions, %s: %d/24 hours had both passes (missing: actions %d, box %d); "
          "%d currency-hours compared; priced on both %d, only on actions %d, only on box %d, withheld on both %d; "
          "index values compared %d, outside %.2f points %d (median diff %s, max %s). %s, clean streak %d"
          % (day, c["hours_both"], c["hours_missing_actions"], c["hours_missing_box"], c["ccy_hours_compared"],
             c["priced_both"], c["priced_only_actions"], c["priced_only_box"], c["withheld_both"],
             c["index_compared"], INDEX_TOL, c["index_mismatch"], c["index_abs_diff_median"],
             c["index_abs_diff_max"], "CLEAN" if c["clean"] else "NOT CLEAN", c["clean_streak"]))
    if a.dry_run:
        return 0

    os.makedirs(os.path.join(STATE, "compare_detail"), exist_ok=True)
    p = os.path.join(STATE, "compare_daily.csv")
    rows = [r for r in read_daily() if r["date"] != day]  # re-running a day replaces its line
    rows.append({k: c.get(k, "") for k in DAILY_FIELDS})
    rows.sort(key=lambda r: r["date"])
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(STATE, "compare_detail", day + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(DETAIL_FIELDS)
        w.writerows(detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
