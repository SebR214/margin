#!/usr/bin/env python3
"""Rot guard for the collect and fee workflows.

The old guard was "this run staged no changes -> fail". That was a good proxy
for rot right up until the schedule started firing twice an hour (:17 and :47)
with a per-hour idempotency gate: from then on, *every* second fire of a
healthy hour stages nothing and would have gone red. Redundancy would have read
as failure, which is the fastest way to get a red build ignored.

So the guard moved from "did this fire write?" to the thing it was always
actually asking: "is the newest row recent enough?". A deduped fire is silent;
a collector that has genuinely stopped landing rows is not.

One global limit stopped being honest once a monthly file joined the two
hourly ones (SEB-36): 3h is a real stall for `samples.csv` and `basis.csv`,
whose schedule is hourly, and completely ordinary for `fee_checks.csv` and
`withdrawal_fees.csv`, which are only supposed to move once a month. Each
target below carries its own limit instead.

Exit 0 = every file fresh. Exit 1 = any file stale (or unreadable), with the
reason on stderr.
"""

import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Hourly collectors: worst observed GitHub scheduler drop before
# over-scheduling was two consecutive hours, so 3h past due is a real stall.
HOURLY_MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "3"))
# Monthly fee watcher: the check fires once a month (cron `23 3 1 * *`). 35
# days gives it a few days' grace past a dropped or delayed fire before the
# freshness gate itself goes red.
FEE_MAX_AGE_HOURS = float(os.environ.get("FEE_MAX_AGE_DAYS", "35")) * 24

# (path, timestamp column, max age in hours).
TARGETS = [
    (os.path.join(HERE, "data", "samples.csv"), "ts", HOURLY_MAX_AGE_HOURS),
    (os.path.join(HERE, "data", "basis.csv"), "ts_utc", HOURLY_MAX_AGE_HOURS),
    (os.path.join(HERE, "data", "fee_checks.csv"), "ts_utc", FEE_MAX_AGE_HOURS),
    (os.path.join(HERE, "data", "withdrawal_fees.csv"), "ts_utc", FEE_MAX_AGE_HOURS),
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


def fmt_age(hours, limit_hours):
    """Age and its limit, in whichever unit reads honestly -- a 35-day limit
    printed as "840.0h" obscures the schedule it is measuring against."""
    if limit_hours >= 48:
        return f"{hours / 24:.1f}d old (limit {limit_hours / 24:.0f}d)"
    return f"{hours:.1f}h old (limit {limit_hours:.0f}h)"


def main():
    now = dt.datetime.now(dt.timezone.utc)
    stale = []
    for path, field, max_age in TARGETS:
        name = os.path.basename(path)
        ts = last_ts(path, field)
        if ts is None:
            stale.append(f"{name}: no readable rows")
            continue
        age = (now - ts).total_seconds() / 3600
        mark = "ok" if age <= max_age else "STALE"
        print(f"  [{mark}] {name}: newest row {ts:%Y-%m-%dT%H:%M}Z, "
              f"{fmt_age(age, max_age)}")
        if age > max_age:
            stale.append(f"{name}: {fmt_age(age, max_age)}")

    if stale:
        print(f"\n  [error] data is rotting -- {'; '.join(stale)}", file=sys.stderr)
        sys.exit(1)
    print("  freshness ok")


if __name__ == "__main__":
    main()
