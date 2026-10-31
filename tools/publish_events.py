#!/usr/bin/env python3
"""data/events_published.json: which detected events get a page (SEB-423 step 2). Plain code, no model.

An event is published when its newest candidate row says "two sources" and either
  - an official break moved the official rate 10% or more, or a street slide moved the street price 15% or more, or
  - its record holds a hand-entered known_date with a url (as the Iraq record does).
Candidates come from data/events.csv (observed by our collectors, record in data/event_records/) and from
data/history/events_reported_rules4.csv (replayed over history files, "reported, not observed", record in
data/history/event_records_rules4/). An id in both is taken from the observed file.

The file lists newest first: {"as_of": date of the newest source row, "rules": {...},
 "events": [{id, ccy, event_kind, date, change_pct, confirmation, label, record}]}. `record` is the path of the record JSON.
The daily detector run (03 UTC) adds candidates; this tool runs right after it and a page appears the day a candidate has two sources.

    python3 tools/publish_events.py [--self-test]
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "events_published.json")
OFFICIAL_MIN = 10.0
STREET_MIN = 15.0
SOURCES = [("events.csv", "event_records", "observed"),
           (os.path.join("history", "events_reported_rules4.csv"), os.path.join("history", "event_records_rules4"), "reported, not observed")]


def read(path):
    p = os.path.join(DATA, path)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def has_known(record_dir, eid):
    p = os.path.join(DATA, record_dir, eid + ".json")
    if not os.path.exists(p):
        return False
    k = (json.load(open(p)) or {}).get("known_date") or {}
    return bool(k.get("date") and k.get("url"))


def qualifies(row, known):
    if row["status"] != "candidate":
        return False
    pct = abs(float(row["change_pct"]))
    big = pct >= (OFFICIAL_MIN if row["kind"] == "official_break" else STREET_MIN)
    return (row["confirmation"] == "two sources" and big) or known


def select(sources, known=has_known):
    """sources: [(rows, record_dir, label)] in priority order. Returns the published events, newest first."""
    seen, out = set(), []
    for rows, record_dir, label in sources:
        for r in rows:
            if r["status"] != "candidate" or r["event_id"] in seen:
                continue
            if not qualifies(r, known(record_dir, r["event_id"])):
                continue
            seen.add(r["event_id"])
            out.append({"id": r["event_id"], "ccy": r["ccy"], "event_kind": r["kind"], "date": r["as_of_date"],
                        "change_pct": round(float(r["change_pct"]), 1), "confirmation": r["confirmation"], "label": label,
                        "record": "data/%s/%s.json" % (record_dir.replace(os.sep, "/"), r["event_id"])})
    out.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return out


def self_test():
    row = lambda i, k, st, c, p: {"event_id": i, "kind": k, "status": st, "confirmation": c, "change_pct": str(p), "ccy": i[:3], "as_of_date": "2026-01-01"}
    none = lambda d, i: False
    rows = [row("AAA-official_break-1", "official_break", "candidate", "two sources", -12),
            row("BBB-official_break-1", "official_break", "candidate", "two sources", 9.9),
            row("CCC-official_break-1", "official_break", "candidate", "one source", 40),
            row("DDD-street_slide-1", "street_slide", "candidate", "two sources", 14.9),
            row("EEE-street_slide-1", "street_slide", "candidate", "two sources", 15),
            row("FFF-official_break-1", "official_break", "update", "two sources", 50)]
    got = [e["id"] for e in select([(rows, "x", "observed")], none)]
    assert sorted(got) == ["AAA-official_break-1", "EEE-street_slide-1"], got
    got = [e["id"] for e in select([(rows, "x", "observed")], lambda d, i: i.startswith("CCC"))]
    assert "CCC-official_break-1" in got and "BBB-official_break-1" not in got, got
    dup = select([(rows[:1], "a", "observed"), (rows[:1], "b", "reported, not observed")], none)
    assert len(dup) == 1 and dup[0]["label"] == "observed"
    print("self-test ok")
    return 0


def main():
    srcs = [(read(f), d, label) for f, d, label in SOURCES]
    events = select(srcs)
    dates = [r["as_of_date"] for rows, _, _ in srcs for r in rows]
    doc = {"as_of": max(dates) if dates else None, "rules": {"official_break_min_pct": OFFICIAL_MIN, "street_slide_min_pct": STREET_MIN,
           "needs": "two sources, or a hand-entered known_date with a url"}, "events": events}
    new = json.dumps(doc, indent=1) + "\n"
    old = open(OUT).read() if os.path.exists(OUT) else ""
    if new != old:
        with open(OUT, "w") as f:
            f.write(new)
    print("%d events published" % len(events))
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
