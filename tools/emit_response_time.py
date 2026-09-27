#!/usr/bin/env python3
"""How many hours after the official rate moves does the street price follow?
Builds data/response_time_latest.json. Stdlib only.

THE PROBLEM: there is no hourly history sitting in a file anywhere.

Each data/countries/<CCY>.json carries a `history` array, but it is DAILY --
one point per calendar day, going back to 2024, with nothing in it but the
premium (`index_pct`). It has no separate official-rate series and no hourly
resolution at all. The only place both series exist hour by hour is where
this whole site already keeps every hourly snapshot: git itself. Since commit
066c03f12 ("Per-country index files..."), a scheduled job commits every
country's JSON once an hour ("sample <timestamp>" commits). Reading those
commits back in order, for one file, IS the hourly time series -- there is no
other source of it. `_hourly_series()` below does exactly that: it walks
`git log -p -U0` for one country's file and reconstructs, hour by hour, the
official rate (`denominator.rate_per_usd`) and the published street premium
(`index_pct`) by replaying only the lines a diff shows as added, carrying
forward whatever field did not change that hour.

That also means the real amount of hourly history is bounded by when
per-country files started, 2026-09-10 -- about 17 days / ~390 hours as of
this writing, no matter what `history_days` says (that field counts the
DAILY backfill since 2024 and is irrelevant here; it is never read by this
script). 17 days is a hard ceiling, not a design choice, and it is also why
this file will read as noisier the further in the past someone reads this
comment: more history accumulates every day the collector keeps running.

MINIMUM HISTORY: MIN_HOURS = 300 (12.5 days). Below that, a country is
skipped -- not published with a number, not extrapolated, just left out with
a reason, same as this site's other "not enough data" gaps. Reasoning for
the number: 17 days is ALL the hourly history that exists for anybody,
market-wide, so the only real lever is how much of that any one country
actually has (a few files have short gaps from collector outages). 300
hours means at most about 90 hours of gap is tolerated out of the ~390-hour
maximum -- comfortably covers the two ~21-hour outages every country shares
-- while still refusing a country whose file is missing several days of
runs. This is a floor on RAW COVERAGE, separate from the floor on actual
usable EVENTS below.

THE METHOD: an event study on the official rate's own step changes.

Both series update every hour, but the official rate (`denominator.rate_per_usd`,
whatever source is behind it for that country: a market quote, a managed
peg, a parallel-market cross-check) does NOT drift continuously in this
data -- it holds a flat value for many hours, then jumps, because its
upstream source only refreshes itself every so often. That is a real,
convenient fact about this dataset: it turns "when did the official rate
move" into "find the step," not "estimate a slope." A cross-correlation
between two continuously-varying series was considered and rejected for
that reason -- it wants continuous variation on both sides, and one side
here is piecewise constant.

For each country:
  1. Find every hour where the official rate changed by more than
     EVENT_THRESH_PCT (0.05%) from the hour before -- a detected "event."
  2. For each event, take the median premium (`index_pct`) over the up to
     6 hours right before it as the baseline -- what the premium was
     "supposed to" look like. A rate jump moves the premium mechanically
     the instant it posts, before the street has had any chance to react
     (premium = street vs. official, and official just moved), so the
     hour of the event itself already shows a distorted premium.
  3. Skip events whose mechanical shift is under 0.05 percentage points --
     too small to separate from ordinary hour-to-hour noise in the premium.
  4. Walk forward hour by hour and record the first hour where the premium
     has closed at least 70% of that gap back toward the baseline
     (REVERSION_FRAC = 0.3, i.e. residual gap has SHRUNK to <=30% of what
     it started at). That is the plain-English "the street caught up":
     the premium is back to roughly where it was before the official rate
     moved, which only happens once the street price itself has moved to
     match. The search stops at the next detected event (so one jump's
     recovery is never mistaken for a different jump's), or after
     MAX_WINDOW_HOURS, whichever comes first.
  5. The lag is measured in real elapsed hours between the two hours'
     timestamps, not a row count -- a small number of collector gaps
     (~21h, shared by every country) would otherwise silently compress or
     inflate a lag that happened to straddle one.
  6. A country's headline number is the MEDIAN lag across its own resolved
     events. Events that never reverted within the window are counted and
     reported but do not enter the median.

CONFIDENCE, separate from the MIN_HOURS coverage floor: a country needs at
least one resolved event to be published at all (fewer than that is "not
enough history yet," same reason as MIN_HOURS -- there is nothing to
measure). Above that:
  low    1-3 resolved events
  medium 4-7 resolved events
  high   8+  resolved events
This is a count of independent real-world rate-move events actually
witnessed reverting, not a statistical interval -- read "low confidence" as
"take this as a first read, not a settled number."

A country whose official rate never moves at all in 17 days (a hard USD
peg) produces zero events and is correctly excluded -- there is nothing to
measure a reaction to, not a data gap.

Derived, never authoritative. Re-running this script queries git history
(read-only) and recomputes everything; it writes no history of its own and
changes nothing else in the repo.

Usage: python3 tools/emit_response_time.py
"""

import datetime as dt
import glob
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
COUNTRIES_DIR = os.path.join(DATA, "countries")
OUT_JSON = os.path.join(DATA, "response_time_latest.json")

MIN_HOURS = 300          # 12.5 days of the ~390-hour maximum available; see docstring
EVENT_THRESH_PCT = 0.05  # % move in the official rate to count as a step
MIN_GAP_PP = 0.05        # percentage points of mechanical premium shift, floor
REVERSION_FRAC = 0.30    # residual gap must shrink to <= this fraction of its start
MAX_WINDOW_HOURS = 240   # 10 days; give a slow reactor room without searching forever
BASELINE_LOOKBACK = 6    # hours before the event used to set the "before" premium

RE_TOP_BUY_PRICE = re.compile(r'^\+  "buy_price": ([\-\d.]+),?$')
RE_TOP_BUY_PRICE_REMOVED = re.compile(r'^-  "buy_price"')
RE_HOUR_UTC = re.compile(r'^\+  "hour_utc": "([^"]+)",?$')
RE_TOP_INDEX_PCT = re.compile(r'^\+  "index_pct": ([\-\d.]+),?$')
RE_RATE_PER_USD = re.compile(r'^\+    "rate_per_usd": ([\-\d.]+),?$')


def _run_git_log(rel_path):
    out = subprocess.run(
        ["git", "log", "-p", "-U0", "--format=COMMIT %H|%ad",
         "--date=iso-strict", "--reverse", "--", rel_path],
        cwd=HERE, capture_output=True, text=True, check=False,
    )
    return out.stdout.splitlines()


def hourly_series(ccy):
    """Replay every hourly commit to data/countries/<ccy>.json into a list of
    {hour_utc, buy_price, official_rate, index_pct}, oldest first. A field
    absent from a given commit's diff carries forward its last known value,
    since a unified diff with zero context only ever shows what changed."""
    rel = f"data/countries/{ccy}.json"
    lines = _run_git_log(rel)
    points = []
    state = {"buy_price": None, "official_rate": None, "index_pct": None, "hour_utc": None}
    touched = False

    def flush():
        if touched and state["hour_utc"]:
            points.append(dict(state))

    for line in lines:
        if line.startswith("COMMIT "):
            flush()
            touched = False
            continue
        m = RE_TOP_BUY_PRICE.match(line)
        if m:
            state["buy_price"] = float(m.group(1))
            touched = True
            continue
        if RE_TOP_BUY_PRICE_REMOVED.match(line):
            state["buy_price"] = None
            touched = True
            continue
        m = RE_HOUR_UTC.match(line)
        if m:
            state["hour_utc"] = m.group(1)
            touched = True
            continue
        m = RE_TOP_INDEX_PCT.match(line)
        if m:
            state["index_pct"] = float(m.group(1))
            touched = True
            continue
        m = RE_RATE_PER_USD.match(line)
        if m:
            state["official_rate"] = float(m.group(1))
            touched = True
            continue
    flush()
    return points


def _parse_hour(h):
    return dt.datetime.fromisoformat(h.replace("Z", "+00:00"))


def analyze_country(ccy, country_name):
    raw = hourly_series(ccy)
    series = [p for p in raw if p["official_rate"] is not None and p["index_pct"] is not None]

    if len(series) < MIN_HOURS:
        return {"ccy": ccy, "country": country_name, "status": "not_enough_history",
                "hours_of_data": len(series)}

    official = [p["official_rate"] for p in series]
    premium = [p["index_pct"] for p in series]
    hours = [p["hour_utc"] for p in series]

    event_idx = []
    for i in range(1, len(series)):
        prev, cur = official[i - 1], official[i]
        if prev == 0 or cur == prev:
            continue
        if abs(cur - prev) / abs(prev) * 100 > EVENT_THRESH_PCT:
            event_idx.append(i)

    resolved, unresolved_events = [], []
    for pos, idx in enumerate(event_idx):
        lo = max(0, idx - BASELINE_LOOKBACK)
        baseline_window = premium[lo:idx]
        if len(baseline_window) < 3:
            continue
        baseline = statistics.median(baseline_window)
        immediate = premium[idx]
        gap = immediate - baseline
        if abs(gap) < MIN_GAP_PP:
            continue  # official move too small to leave a visible mechanical mark

        next_idx = event_idx[pos + 1] if pos + 1 < len(event_idx) else None
        window_end = min(len(series) - 1, idx + MAX_WINDOW_HOURS)
        if next_idx is not None:
            window_end = min(window_end, next_idx)

        target_resid = abs(gap) * REVERSION_FRAC
        found_at = None
        for j in range(idx, window_end + 1):
            if abs(premium[j] - baseline) <= target_resid:
                found_at = j
                break

        event_row = {
            "event_hour": hours[idx],
            "official_before": official[idx - 1],
            "official_after": official[idx],
            "pct_move": round((official[idx] - official[idx - 1]) / official[idx - 1] * 100, 4),
            "premium_before": round(baseline, 4),
            "premium_immediate": round(immediate, 4),
        }
        if found_at is not None:
            lag_hours = round(
                (_parse_hour(hours[found_at]) - _parse_hour(hours[idx])).total_seconds() / 3600.0, 1
            )
            event_row["lag_hours"] = lag_hours
            resolved.append(event_row)
        else:
            event_row["lag_hours"] = None
            unresolved_events.append(event_row)

    if not resolved:
        return {"ccy": ccy, "country": country_name, "status": "no_resolved_events",
                "hours_of_data": len(series), "n_events_detected": len(event_idx),
                "n_unresolved": len(unresolved_events)}

    lags = [r["lag_hours"] for r in resolved]
    n = len(resolved)
    confidence = "high" if n >= 8 else "medium" if n >= 4 else "low"

    return {
        "ccy": ccy,
        "country": country_name,
        "status": "ok",
        "hours_of_data": len(series),
        "median_response_hours": statistics.median(lags),
        "n_events_resolved": n,
        "n_events_detected": len(event_idx),
        "n_events_unresolved": len(unresolved_events),
        "confidence": confidence,
        # Average absolute premium over the whole measured window -- used
        # only to check, honestly, whether a wider premium tracks a slower
        # reaction (see _premium_lag_correlation). Not itself a headline
        # number anywhere else on the site.
        "premium_avg_abs": round(statistics.mean(abs(p) for p in premium), 4),
        "events": resolved,
        "unresolved_events": unresolved_events,
    }


def _premium_lag_correlation(qualified):
    """Pearson r between a country's median response lag and its average
    absolute premium, across every qualified country. This exists to check
    the hypothesis this feature started from -- "the slower a market
    reprices, the wider its premium sits" -- against the real numbers,
    honestly, rather than asserting it. Returns None if fewer than 3 points."""
    xs = [c["median_response_hours"] for c in qualified]
    ys = [c["premium_avg_abs"] for c in qualified]
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return round(cov / (sx * sy), 4)


def main():
    paths = sorted(glob.glob(os.path.join(COUNTRIES_DIR, "*.json")))
    countries = []
    for p in paths:
        ccy = os.path.splitext(os.path.basename(p))[0]
        with open(p) as f:
            country_name = json.load(f).get("country", ccy)
        countries.append((ccy, country_name))

    rows = [analyze_country(ccy, name) for ccy, name in countries]
    qualified = [r for r in rows if r["status"] == "ok"]
    not_qualified = [r for r in rows if r["status"] != "ok"]

    doc = {
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method": "event_study_official_rate_steps",
        "min_hours_required": MIN_HOURS,
        "event_threshold_pct": EVENT_THRESH_PCT,
        "reversion_fraction": REVERSION_FRAC,
        "max_window_hours": MAX_WINDOW_HOURS,
        "premium_lag_correlation": _premium_lag_correlation(qualified),
        "n_countries_total": len(rows),
        "n_countries_qualified": len(qualified),
        "countries": sorted(qualified, key=lambda r: r["median_response_hours"]),
        "not_enough_data": sorted(
            [{"ccy": r["ccy"], "country": r["country"], "status": r["status"],
              "hours_of_data": r.get("hours_of_data"),
              "n_events_detected": r.get("n_events_detected")}
             for r in not_qualified],
            key=lambda r: r["country"],
        ),
    }

    with open(OUT_JSON, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")

    print(f"{len(qualified)}/{len(rows)} countries qualified -> {OUT_JSON}", file=sys.stderr)


if __name__ == "__main__":
    main()
