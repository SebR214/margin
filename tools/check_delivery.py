#!/usr/bin/env python3
"""How many hours a day did the collector actually run?

`check_freshness.py` is the guard: it asks "is the newest row recent enough?"
and exits non-zero when it isn't. That catches a collector which has stopped
writing. It cannot catch a fire that never happened -- a run which is dropped by
the scheduler leaves no trace at all, and the next run that does fire writes a
perfectly fresh row, so the guard stays green through a five-hour hole.

This is the missing measurement. It counts DISTINCT UTC hours present in
`data/basis.csv` per day, which is the same thing as "how many times did the
workflow reach the basis collector that day", because the collector writes one
batch per hour and is idempotent within it. A partial pull still counts: rows
with `source_ok=False` are a fire that happened and a venue that didn't, and the
question here is only whether the fire happened.

This is a measurement tool, not a guard. It always exits 0. Nothing should ever
go red because delivery is bad -- that judgement is Sebastian's, against the
target in ROADMAP P0-1, not a threshold buried in a script.
"""

import collections
import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASIS = os.path.join(HERE, "data", "basis.csv")
DAYS = 14


def hours_by_day(path):
    """{date -> set of UTC hours with at least one row}."""
    seen = collections.defaultdict(set)
    if not os.path.exists(path):
        return seen
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("ts_utc") or "").strip()
            if not raw:
                continue
            try:
                ts = dt.datetime.fromisoformat(raw)
            except ValueError:
                # A malformed row is not a delivery signal either way. Skip it
                # rather than guessing -- and rather than dying, since this
                # tool must never be the reason a run goes red.
                continue
            if ts.tzinfo is not None:
                ts = ts.astimezone(dt.timezone.utc)
            seen[ts.date()].add(ts.hour)
    return seen


def main():
    seen = hours_by_day(BASIS)
    if not seen:
        print(f"  no readable rows in {os.path.relpath(BASIS, HERE)}")
        return

    today = dt.datetime.now(dt.timezone.utc).date()
    for offset in range(DAYS - 1, -1, -1):
        day = today - dt.timedelta(days=offset)
        n = len(seen.get(day, ()))
        note = "  <- today, still filling" if day == today else ""
        print(f"  {day}  {n:2d}/24{note}")


if __name__ == "__main__":
    main()
    sys.exit(0)
