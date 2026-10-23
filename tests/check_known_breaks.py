#!/usr/bin/env python3
"""The known-breaks test (SEB-311 step 3c): the event detector, replayed over the history files in data/history/, must find the breaks
we know happened, and must miss the one we know it cannot see, for the reason written below. Offline, nothing written.

  Turkey, Aug 2018        a candidate in August 2018
  Turkey, Nov-Dec 2021    a candidate between 10 Nov and 31 Dec 2021
  Argentina, 14 Dec 2023  a candidate on 14 Dec 2023, or (rules version 3, one event per currency per 30 days) a further official break of
                          +118.7% on the event already open (the rate went from 366 to 800 in a day)
  Egypt, Mar 2024         a row on 7 Mar 2024, a candidate or "not enough evidence" (the float of 6 Mar, +60%; only 6 days of
                          official history exist before it, so "not enough evidence" is the correct reading)
  Iraq, Oct 2026          a candidate in the week of 7 Oct 2026 (the government raised the official rate)
  Nigeria, Jun 2023       FOUND AS A DATA WARNING, NOT AS A CANDIDATE. Frankfurter v2 (SEB-311, rules 4 replay) gives the official naira from
                          29 Dec 2017, and its 15 Jun 2023 reading is +25.3% in a day (472.61 to 580.61), so the break is seen. It is held, not
                          an event, because a step of 10% or more needs a second stored source and fawazahmed0 only starts on 2 Mar 2024. If a
                          second source before that date is ever stored, this becomes a candidate and the expectation must be rewritten.

Rules version 4 also holds: BOB 8 Jul 2026 and SYP 22 Oct 2025, data warnings under rules 3, are candidates now that a second stored source
covers those days; and no currency has two candidates less than 30 days apart.

Also: the committed data/history/events_reported_rules4.csv holds the same number of candidates as a fresh replay, so the file in the repo
is what these rules produce.

    python3 tests/check_known_breaks.py
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import backfill_history as bh  # noqa: E402
import detect_events as de  # noqa: E402

data, names, snames = bh.history_data()
last = max(d for v in data["off"].values() for d in v)
rows, _ = de.run_days(data, [], de.first_day(data), last)
again, _ = de.run_days(data, [], de.first_day(data), last)
assert rows == again, "the replay gave different rows on a second run"


def found(ccy, a, b, statuses=("candidate",), kind="official_break"):
    return [r for r in rows if r["ccy"] == ccy and r["kind"] == kind and r["status"] in statuses and a <= r["detected_on"] <= b]


def need(label, hits):
    assert hits, "known break not found: %s" % label
    print("  found  %-24s %s" % (label, ", ".join("%s %s %s%%" % (r["detected_on"], r["status"], r["change_pct"]) for r in hits[:3])))


need("Turkey Aug 2018", found("TRY", "2018-08-01", "2018-08-31"))
need("Turkey Nov-Dec 2021", found("TRY", "2021-11-10", "2021-12-31"))
# Under the 30-day rule the 14 Dec devaluation is not an event of its own: Argentina already had an open event (the street slides of
# 19 Nov and 7 Dec), so the +119% is recorded as a further official break on it. It must be there with its size.
ars = found("ARS", "2023-12-14", "2023-12-14") or [r for r in rows if r["ccy"] == "ARS" and r["status"] == "update" and r["as_of_date"] == "2023-12-14"
                                                   and "a further official break of 118." in r["note"]]
need("Argentina 14 Dec 2023", ars)
need("Egypt Mar 2024", found("EGP", "2024-03-07", "2024-03-07", ("candidate", "not_enough_evidence")))
need("Iraq Oct 2026", found("IQD", "2026-10-07", "2026-10-14"))

first_ngn = min(data["off"]["NGN"])
assert first_ngn <= "2023-05-01", "the naira official history starts %s, after Jun 2023: the Nigeria expectation no longer holds" % first_ngn
ngn = found("NGN", "2023-06-14", "2023-06-16", ("data_warning",))
need("Nigeria Jun 2023 (held)", ngn)
assert not found("NGN", "2023-05-15", "2023-07-15"), "Nigeria Jun 2023 now stands as a candidate: a second source before Mar 2024 exists, rewrite the expectation"
assert min(data["live"]["NGN"]) >= "2024-03-01", "a second naira source now reaches back to %s: Nigeria Jun 2023 may stand, rewrite the expectation" % min(data["live"]["NGN"])

# the rules are the ones written down: a managed currency keeps the 3%, every other needs 4x its own median
managed = data["managed"]
assert {"ARS", "IQD", "NGN", "VES", "SYP"} <= managed and not ({"TRY", "EGP", "ZAR"} & managed), sorted(managed)
for r in rows:
    if r["status"] == "candidate" and r["kind"] == "official_break" and r["ccy"] not in managed:
        m, n = de.own_median_move(data, r["ccy"])(r["detected_on"])
        assert n >= de.MIN_BASELINE_PAIRS and abs(float(r["change_pct"])) >= de.OWN_MULT * m, r

# a unit error is never an event: no jump of 50% or more stands without a central-bank series or a second source that shows it
for r in rows:
    if r["status"] == "candidate" and r["kind"] == "official_break" and abs(float(r["change_pct"])) >= de.JUMP_HOLD_PCT:
        assert r["ccy"] in data["central_bank"] or data["live"].get(r["ccy"], {}).get(r["detected_on"]), \
            "a jump of 50%% or more in an aggregator feed with no second source stood as an event: %s" % r
for ccy in ("VES", "SYP", "MNT"):
    assert not [r for r in rows if r["ccy"] == ccy and r["status"] == "candidate" and abs(float(r["change_pct"])) >= de.JUMP_HOLD_PCT], ccy

# rules version 3 held BOB 8 Jul 2026 and SYP 22 Oct 2025 as data warnings (no second stored source). With Frankfurter v2 as the official series
# and fawazahmed0 as the second source, both days now have one, so both stand as candidates
for ccy, day in (("BOB", "2026-07-08"), ("SYP", "2025-10-22")):
    assert found(ccy, day, day) and data["live"][ccy].get(day), "%s %s must stand as a candidate: fawazahmed0 shows the step" % (ccy, day)
by_ccy = {}
for r in rows:
    if r["status"] == "candidate":
        by_ccy.setdefault(r["ccy"], []).append(r["detected_on"])
for ccy, ds in by_ccy.items():
    for a, b in zip(ds, ds[1:]):
        assert (de.dt.date.fromisoformat(b) - de.dt.date.fromisoformat(a)).days >= de.EVENT_WINDOW_DAYS, "%s: two events %s and %s inside %d days" % (ccy, a, b, de.EVENT_WINDOW_DAYS)
for r in rows:
    if r["status"] == "candidate" and r["kind"] == "official_break" and abs(float(r["change_pct"])) >= de.SECOND_SOURCE_PCT:
        assert r["ccy"] in data["central_bank"] or (r["ccy"] in data["live"] and data["live"][r["ccy"]].get(r["detected_on"])), "a step of 10%% or more with no second source behind it stood: %s" % r

# the file in the repo is what these rules produce
path = os.path.join(ROOT, "data", "history", "events_reported_rules4.csv")
with open(path, newline="") as f:
    filed = list(csv.DictReader(f))
assert {r["rules_version"] for r in filed} == {str(bh.HISTORY_RULES_VERSION)}, "the rules4 file holds another rules version"
n_file = sum(1 for r in filed if r["status"] == "candidate")
n_now = sum(1 for r in rows if r["status"] == "candidate")
assert n_file == n_now, "events_reported_rules4.csv has %d candidates, a fresh replay %d: rerun backfill_history.py --replay" % (n_file, n_now)
print("check_known_breaks: ok (%d candidates)" % n_now)
