#!/usr/bin/env python3
"""A forward-looking record of currencies pulling away from their official
rate. Writes data/stress_signal.csv (append-only) and
data/stress_signal_latest.json, which stress.html reads.

THE DECISION THIS FILE IMPLEMENTS (Linear SEB-33, chosen 2026-09-13):
`data/fx_rates.csv` only starts on 2026-09-10, so there is no history long
enough to backtest the stress signal against a real devaluation. Backfilling
it would break the project's oldest rule -- nothing is ever backfilled -- so
instead this keeps score from here on. The record is honest about being short:
every day it has not run is a day of evidence it does not have, and the page
says so in as many words.

THE TRIGGER is the same "moves_unexplained" check tools/agent_status.py
already runs against the published index, reused rather than reinvented and
kept here as a public, permanent record instead of an internal health check:

  a currency's daily premium (`index_pct` in data/countries/<CCY>.json) pulls
  AWAY from the official rate -- its distance from zero grows by more than
  WIDEN_THRESHOLD_PT in a single day -- while the official rate itself
  (`data/fx_rates.csv`) moved by less than FX_EXPLAINS_PCT. A currency whose
  official rate also moved is not a street-price story; it is just the
  currency, and agent_status.py already excludes exactly that case.

Only days on or after the first day fx_rates.csv actually has are checked --
nothing before the record's own start can be judged, so nothing before it is.
Only COMPLETE days are judged (today is always still filling), and only a
day-over-day pair that is truly one calendar day apart is compared, so a gap
in a currency's own history is never read as a single day's move.

Append-only and idempotent: a (currency, day) pair already in the CSV is
never re-checked or rewritten.

Stdlib only. Usage: python3 tools/emit_stress_signal.py
"""

import csv
import datetime as dt
import glob
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
COUNTRIES = os.path.join(DATA, "countries")
FX = os.path.join(DATA, "fx_rates.csv")
OUT_CSV = os.path.join(DATA, "stress_signal.csv")
OUT_JSON = os.path.join(DATA, "stress_signal_latest.json")

# Frozen from here on; anything new goes in a sidecar file, never a widened
# header.
FIELDS = ["ts_utc", "ccy", "index_pct", "gap_widened_pt", "official_move_pct",
          "triggered_on", "note"]

# The same bar tools/agent_status.py already uses for BIG_MOVE_PT and
# FX_EXPLAINS_PCT. Kept as its own constants here, not imported, so this file
# reads standalone the way every other emitter in tools/ does -- but the
# numbers are the same on purpose.
WIDEN_THRESHOLD_PT = 5.0
FX_EXPLAINS_PCT = 2.0


def num(v):
    try:
        x = float(str(v).strip())
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fx_days_and_daily():
    """Every calendar day data/fx_rates.csv has, and the daily median official
    rate per currency for each of them.
    """
    days = set()
    off = {}
    for r in rows(FX):
        s, c = (r.get("ts_utc") or "").strip(), (r.get("ccy") or "").strip()
        if len(s) < 10 or not c:
            continue
        days.add(s[:10])
        v = num(r.get("fx_mid_per_usd"))
        if v:
            off.setdefault((c, s[:10]), []).append(v)
    return days, {k: st.median(v) for k, v in off.items()}


def country_history():
    """{ccy: {"country": ..., "history": [{date, index_pct}, ...]}}"""
    out = {}
    for path in sorted(glob.glob(os.path.join(COUNTRIES, "*.json"))):
        try:
            with open(path) as f:
                c = json.load(f)
        except (OSError, ValueError):
            continue
        hist = [h for h in (c.get("history") or [])
                if h.get("date") and num(h.get("index_pct")) is not None]
        hist.sort(key=lambda h: h["date"])
        ccy = c.get("ccy")
        if ccy:
            out[ccy] = {"country": c.get("country"), "history": hist}
    return out


def find_triggers(start, judged, countries, official):
    out = []
    for ccy, c in countries.items():
        hist = c["history"]
        for a, b in zip(hist, hist[1:]):
            d_a, d_b = a["date"], b["date"]
            if d_b not in judged or d_a < start or d_b < start:
                continue
            if (dt.date.fromisoformat(d_b) - dt.date.fromisoformat(d_a)).days != 1:
                continue    # a gap in the record, not a one-day move
            i_a, i_b = num(a["index_pct"]), num(b["index_pct"])
            widened = round(abs(i_b) - abs(i_a), 4)
            if widened <= WIDEN_THRESHOLD_PT:
                continue
            f0, f1 = official.get((ccy, d_a)), official.get((ccy, d_b))
            if f0 is None or f1 is None:
                continue    # cannot rule out the official rate explaining it
            official_move = round((f1 - f0) / f0 * 100, 4)
            if abs(official_move) >= FX_EXPLAINS_PCT:
                continue    # the currency moved too -- not a street-price story
            out.append({
                "ts_utc": d_b + "T00:00:00+00:00",
                "ccy": ccy,
                "index_pct": round(i_b, 4),
                "gap_widened_pt": widened,
                "official_move_pct": official_move,
                "triggered_on": d_b,
                "note": (f"{c['country']}'s premium widened by {widened:.2f} "
                         f"points to {i_b:+.2f}% in a day, while its official "
                         f"rate moved {official_move:+.2f}%."),
            })
    out.sort(key=lambda r: (r["triggered_on"], r["ccy"]))
    return out


def add_since(row, official):
    """What the official rate has done since the row's trigger day -- the
    "what happened next" the page keeps score of. Not a CSV column: the CSV
    is frozen at what was true when the row was written, and this changes
    every time a newer sample lands, so it lives only in the JSON, recomputed
    on every run from data/fx_rates.csv.
    """
    ccy, triggered_on = row["ccy"], row["triggered_on"]
    dates = sorted(d for (c, d) in official if c == ccy)
    at_trigger = official.get((ccy, triggered_on))
    latest_date = dates[-1] if dates else None
    latest_rate = official.get((ccy, latest_date)) if latest_date else None
    if at_trigger and latest_rate and latest_date and latest_date > triggered_on:
        row["official_rate_move_since_pct"] = round(
            (latest_rate - at_trigger) / at_trigger * 100, 4)
        row["since_date"] = latest_date
        row["days_since"] = (dt.date.fromisoformat(latest_date)
                              - dt.date.fromisoformat(triggered_on)).days
    else:
        row["official_rate_move_since_pct"] = None
        row["since_date"] = None
        row["days_since"] = 0


def main():
    all_days, official = fx_days_and_daily()
    if not all_days:
        print("  data/fx_rates.csv has no rows yet -- nothing to check")
        payload = {"record_start": None, "as_of": None, "record_days": 0,
                   "threshold_widen_pt": WIDEN_THRESHOLD_PT,
                   "threshold_fx_explains_pct": FX_EXPLAINS_PCT,
                   "triggers": [], "count": 0, "currencies_triggered": []}
        with open(OUT_JSON, "w") as f:
            json.dump(payload, f, indent=1)
            f.write("\n")
        return 0

    start, as_of = min(all_days), max(all_days)
    judged = all_days - {as_of}
    countries = country_history()
    found = find_triggers(start, judged, countries, official)

    existing = rows(OUT_CSV)
    have = {(r["ccy"], r["triggered_on"]) for r in existing}
    fresh = [r for r in found if (r["ccy"], r["triggered_on"]) not in have]

    new_file = not os.path.exists(OUT_CSV)
    if fresh or new_file:
        with open(OUT_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for r in fresh:
                w.writerow(r)
    print(f"  stress_signal.csv: {len(existing)} kept, {len(fresh)} appended")

    allrows = rows(OUT_CSV)
    for r in allrows:
        for k in ("index_pct", "gap_widened_pt", "official_move_pct"):
            r[k] = num(r[k])
        add_since(r, official)
        r["country"] = (countries.get(r["ccy"]) or {}).get("country") or r["ccy"]
    allrows.sort(key=lambda r: (r["triggered_on"], r["ccy"]), reverse=True)

    record_days = len(all_days)
    payload = {
        "record_start": start,
        "as_of": as_of,
        "record_days": record_days,
        "threshold_widen_pt": WIDEN_THRESHOLD_PT,
        "threshold_fx_explains_pct": FX_EXPLAINS_PCT,
        "triggers": allrows,
        "count": len(allrows),
        "currencies_triggered": sorted({r["ccy"] for r in allrows}),
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")
    print(f"  stress_signal_latest.json: {len(allrows)} triggers on record, "
          f"{record_days} days of evidence since {start}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
