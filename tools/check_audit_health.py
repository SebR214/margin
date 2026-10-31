#!/usr/bin/env python3
"""Do the hourly audits say something is wrong, and has it stayed wrong? No
model call. Exit 1 if so (SEB-302).

Reads what tools/audit_numbers.py and tools/audit_claims.py already write:
  data/audit_latest.json + data/audit_history.csv  numbers re-derived from raw rows
  data/claims_status.json + data/claims_history.csv  claims the site makes, re-run
A failed number or a false claim counts once it has been wrong in each of the
last RUNS hourly runs (a single bad hour is not an alarm). The watchdog runs
this.

    python3 tools/check_audit_health.py
    python3 tools/check_audit_health.py --self-test
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RUNS = 3
ACK = os.path.join(DATA, "claims_acknowledged.json")


def acknowledged(today=None, path=ACK):
    """Claims someone has looked at and parked for a decision, with an end date. Still false, still listed in
    the daily status, but they do not fail the watchdog until the date passes: an alarm that rings all night about
    something that is already waiting on a person only teaches people to ignore it."""
    import datetime
    if not os.path.exists(path):
        return {}
    today = today or datetime.date.today().isoformat()
    with open(path) as f:
        doc = json.load(f)
    return {k: v for k, v in (doc.get("claims") or {}).items() if v.get("until", "") >= today}


def last_runs(rows, key, n):
    """The last n distinct run stamps in `rows` (list of dicts), oldest first."""
    seen = []
    for r in rows:
        if r[key] not in seen:
            seen.append(r[key])
    return seen[-n:]


def persistent_false_claims(status, history_rows, runs=RUNS):
    """Claims false now and false in each of the last `runs` runs in the history."""
    now_false = {k: v for k, v in status["claims"].items() if not v.get("ok")}
    stamps = last_runs(history_rows, "as_of_utc", runs)
    out = {}
    for k, v in now_false.items():
        flags = [r["ok"] for r in history_rows if r["key"] == k and r["as_of_utc"] in stamps]
        if len(stamps) >= runs and len(flags) >= runs and all(f == "false" for f in flags):
            out[k] = v
    return out


def persistent_audit_failure(latest, history_rows, runs=RUNS):
    """(True, ids) when the audit had at least one failed number in each of the last `runs` runs."""
    recent = history_rows[-runs:]
    bad = len(recent) >= runs and all(int(r["passed"]) < int(r["drawn"]) for r in recent)
    ids = [f["id"] for f in latest.get("failures", [])] if bad else []
    return bad and bool(latest.get("failed")), ids


def rows(name):
    with open(os.path.join(DATA, name), newline="") as f:
        return list(csv.DictReader(f))


def load():
    with open(os.path.join(DATA, "audit_latest.json")) as f:
        latest = json.load(f)
    with open(os.path.join(DATA, "claims_status.json")) as f:
        status = json.load(f)
    return latest, rows("audit_history.csv"), status, rows("claims_history.csv")


def summary():
    """Everything wrong right now, for the daily status: (failed numbers, false claims), regardless of how long."""
    latest, _, status, _ = load()
    return ([f["id"] for f in latest.get("failures", [])],
            sorted(k for k, v in status["claims"].items() if not v.get("ok")))


def self_test():
    status = {"claims": {"a.ok": {"ok": True}, "b.bad": {"ok": False}, "c.new": {"ok": False}}}
    hist = []
    for t in ("t1", "t2", "t3"):
        hist += [{"as_of_utc": t, "key": "a.ok", "ok": "true"}, {"as_of_utc": t, "key": "b.bad", "ok": "false"}]
    hist += [{"as_of_utc": "t1", "key": "c.new", "ok": "true"}, {"as_of_utc": "t2", "key": "c.new", "ok": "true"},
             {"as_of_utc": "t3", "key": "c.new", "ok": "false"}]
    got = persistent_false_claims(status, hist)
    assert list(got) == ["b.bad"], got                     # a bad claim is caught; a one-hour blip (c.new) is not
    assert persistent_false_claims({"claims": {"a.ok": {"ok": True}}}, hist) == {}
    bad_hist = [{"drawn": "50", "passed": "46"}] * 3
    ok_hist = [{"drawn": "50", "passed": "46"}, {"drawn": "50", "passed": "50"}, {"drawn": "50", "passed": "46"}]
    latest = {"failed": 4, "failures": [{"id": "country:MAD"}]}
    assert persistent_audit_failure(latest, bad_hist) == (True, ["country:MAD"])
    assert persistent_audit_failure(latest, ok_hist)[0] is False
    assert persistent_audit_failure({"failed": 0, "failures": []}, bad_hist)[0] is False
    # an acknowledged claim is listed but does not fail; once its date passes it fails again
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ack.json")
        json.dump({"claims": {"b.bad": {"until": "2026-10-19", "reason": "waiting on words"}}}, open(p, "w"))
        assert "b.bad" in acknowledged("2026-10-15", p) and "b.bad" not in acknowledged("2026-10-20", p)
        assert acknowledged("2026-10-15", os.path.join(d, "none.json")) == {}
    print("check_audit_health self-test: ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    latest, ah, status, ch = load()
    audit_bad, ids = persistent_audit_failure(latest, ah)
    claims = persistent_false_claims(status, ch)
    ack = acknowledged()
    for k in [k for k in claims if k in ack]:
        print("ACKNOWLEDGED until %s: claim %s is false. %s" % (ack[k]["until"], k, ack[k].get("reason", "")))
        del claims[k]
    for i in ids:
        print("DOWN: number %s has not matched its raw rows for %d runs" % (i, RUNS))
    for k in claims:
        print("DOWN: claim %s has been false for %d runs" % (k, RUNS))
    if audit_bad or claims:
        return 1
    print("audits ok: %d of %d numbers matched, %d claims false" % (
        latest.get("passed_count", latest.get("drawn", 0) - latest.get("failed", 0)),
        latest.get("drawn", 0), sum(1 for v in status["claims"].values() if not v.get("ok"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
