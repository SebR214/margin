#!/usr/bin/env python3
"""Rot guard for the collect workflow.

The old guard was "this run staged no changes -> fail". That was a good proxy
for rot right up until the schedule started firing twice an hour (:17 and :47)
with a per-hour idempotency gate: from then on, *every* second fire of a
healthy hour stages nothing and would have gone red. Redundancy would have read
as failure, which is the fastest way to get a red build ignored.

So the guard moved from "did this fire write?" to the thing it was always
actually asking: "is the newest row recent enough?". A deduped fire is silent;
a collector that has genuinely stopped landing rows is not.

Threshold is 3h: the schedule is hourly, and the worst observed GitHub drop
before over-scheduling was two consecutive hours. Anything past that is a real
stall, not scheduler weather.

Exit 0 = fresh. Exit 1 = stale (or unreadable), with the reason on stderr.
"""

import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "3"))

# (path, timestamp column). Only the two layers that must never rot silently --
# providers.csv is supplementary and deliberately not gated.
TARGETS = [
    (os.path.join(HERE, "data", "samples.csv"), "ts"),
    (os.path.join(HERE, "data", "basis.csv"), "ts_utc"),
]


def last_ts(path, field):
    """Timestamp of the final row, or None if the file has no usable rows."""
    if not os.path.exists(path):
        return None
    last = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            last = row
    if not last or not last.get(field):
        return None
    try:
        ts = dt.datetime.fromisoformat(last[field])
    except ValueError:
        return None
    return ts.replace(tzinfo=dt.timezone.utc) if ts.tzinfo is None else ts


def main():
    now = dt.datetime.now(dt.timezone.utc)
    stale = []
    for path, field in TARGETS:
        name = os.path.basename(path)
        ts = last_ts(path, field)
        if ts is None:
            stale.append(f"{name}: no readable rows")
            continue
        age = (now - ts).total_seconds() / 3600
        mark = "ok" if age <= MAX_AGE_HOURS else "STALE"
        print(f"  [{mark}] {name}: newest row {ts:%Y-%m-%dT%H:%M}Z, {age:.1f}h old")
        if age > MAX_AGE_HOURS:
            stale.append(f"{name}: {age:.1f}h old (limit {MAX_AGE_HOURS}h)")

    if stale:
        print(f"\n  [error] data is rotting -- {'; '.join(stale)}", file=sys.stderr)
        sys.exit(1)
    print(f"  freshness ok (limit {MAX_AGE_HOURS}h)")


if __name__ == "__main__":
    main()
