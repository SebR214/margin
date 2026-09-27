#!/usr/bin/env python3
"""How many of the hours we claim to check did we actually check.

Sebastian, in chat 2026-09-27: the site implies "every hour" gets checked for
the sending-money series, but the real collection has real gaps -- the
longest one 21 hours, around 13-14 Sep -- and the site never said so. Charts
that draw a straight line through samples.csv's rows made it worse: a line
chart connects point to point regardless of how much real time sits between
them, so a 21-hour silence reads exactly like the normal ~90-minute cadence.

This script computes the real coverage, per corridor, from data/samples.csv
directly -- never typed, per DESIGN.md ("Numbers are computed from data/,
never typed. Gaps stay gaps.") -- and writes data/coverage.json so
sending-money.html and corridor.html can both show the true number instead
of the implied one.

Coverage, per corridor:
  - n_possible: whole hours from that corridor's first sample to its most
    recent one, inclusive (an hour is identified by its floor, so two
    samples 20 minutes apart in the same clock hour count once).
  - n_checked: how many of those hours have at least one real sample.
  - pct: n_checked / n_possible.
  - longest_gap_hours: the largest gap between two consecutive checked
    hours, and the hour the gap ends at (so a reader can see it really was
    ~13 Sep, not just "a gap exists somewhere").

Also used by corridor.html's history chart to decide where to break the
line: any two consecutive samples more than GAP_THRESHOLD_HOURS apart are a
real gap, not a normal collection interval, and the line should stop instead
of joining them.

Stdlib only. No wall clock in the output (as_of_utc comes from the data's
own latest timestamp, not datetime.now()).

Usage: python3 tools/emit_coverage.py
"""

import csv
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SAMPLES = os.path.join(DATA, "samples.csv")
PROVIDERS_LATEST = os.path.join(DATA, "providers_latest.json")
COPY = os.path.join(HERE, "copy.json")
OUT = os.path.join(DATA, "coverage.json")

# The real collection cadence is roughly hourly to 90 minutes. Anything more
# than double the normal top end is a real silence, not jitter -- this is
# also the threshold corridor.html's chart uses to decide where to break the
# line rather than draw through it.
GAP_THRESHOLD_HOURS = 3


def parse_ts(s):
    return dt.datetime.fromisoformat(s)


def month_day(d):
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return "{} {} {}".format(d.day, months[d.month - 1], d.year)


def build():
    if not os.path.exists(SAMPLES):
        return None

    route_words = {}
    if os.path.exists(PROVIDERS_LATEST):
        with open(PROVIDERS_LATEST) as f:
            doc = json.load(f)
        for k, v in doc.get("corridors", {}).items():
            route_words[k] = v.get("route_words", k)

    hours_by_corridor = {}
    with open(SAMPLES, newline="") as f:
        for row in csv.DictReader(f):
            corridor = (row.get("corridor") or "").strip()
            ts = (row.get("ts") or "").strip()
            if not corridor or not ts:
                continue
            hour = parse_ts(ts).replace(minute=0, second=0, microsecond=0)
            hours_by_corridor.setdefault(corridor, set()).add(hour)

    corridors = {}
    for corridor, hours in hours_by_corridor.items():
        ordered = sorted(hours)
        start, end = ordered[0], ordered[-1]
        n_possible = int((end - start).total_seconds() // 3600) + 1
        n_checked = len(ordered)

        longest_gap_hours = 0
        longest_gap_end = None
        for prev, cur in zip(ordered, ordered[1:]):
            gap = (cur - prev).total_seconds() / 3600
            if gap > longest_gap_hours:
                longest_gap_hours = gap
                longest_gap_end = cur

        pct = round(n_checked / n_possible * 100, 1) if n_possible else 0.0

        corridors[corridor] = {
            "route_words": route_words.get(corridor, corridor),
            "n_checked": n_checked,
            "n_possible": n_possible,
            "pct": pct,
            "start_utc": start.isoformat() + "+00:00" if start.tzinfo is None else start.isoformat(),
            "as_of_utc": end.isoformat() + "+00:00" if end.tzinfo is None else end.isoformat(),
            "longest_gap_hours": round(longest_gap_hours),
            "longest_gap_end_utc": (
                (longest_gap_end.isoformat() + "+00:00" if longest_gap_end.tzinfo is None else longest_gap_end.isoformat())
                if longest_gap_end else None
            ),
            "start_words": month_day(start),
            "longest_gap_end_words": month_day(longest_gap_end) if longest_gap_end else None,
        }

    sentence_template = None
    if os.path.exists(COPY):
        with open(COPY) as f:
            copy_doc = json.load(f)
        sentence_template = (copy_doc.get("sendingMoney") or {}).get("coverageTemplate")

    if sentence_template:
        for corridor, c in corridors.items():
            c["sentence"] = (
                sentence_template
                .replace("{checked}", "{:,}".format(c["n_checked"]))
                .replace("{possible}", "{:,}".format(c["n_possible"]))
                .replace("{pct}", "{:g}".format(c["pct"]))
                .replace("{start}", c["start_words"])
                .replace("{gapHours}", str(c["longest_gap_hours"]))
                .replace("{gapEnd}", c["longest_gap_end_words"] or "")
            )

    return {"gap_threshold_hours": GAP_THRESHOLD_HOURS, "corridors": corridors}


def main():
    out = build()
    if out is None:
        return
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
