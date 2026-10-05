#!/usr/bin/env python3
"""data/record_milestones.json: the real date each source, route and backfill series
first appears in the stored data, oldest first.

Schema
    {
      "as_of_utc": newest stored reading timestamp,
      "definition": how a first date is found,
      "milestones": [
        {"kind": "source" | "route" | "backfill",
         "id": the name as stored (venue, source, corridor, or the backfill manifest key),
         "first_utc": "YYYY-MM-DDTHH:MM:SSZ",
         "first_day": "YYYY-MM-DD"}
        ...sorted by first_utc, then kind, then id...
      ]
    }
source / route: the earliest stored successful reading (record_common's definition),
from 2026-08-10. backfill: the `first` date of each series in the backfill manifest
(data/history/manifest.json), reported not observed; read here only for its first dates,
like tools/emit_country_history.py, and listed in tools/check_history_isolation.py.
Stored files only; no wall clock; stdlib only.

Usage: python3 tools/emit_record_milestones.py [--self-test]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

OUT = os.path.join(rc.DATA, "record_milestones.json")
MANIFEST = os.path.join(rc.DATA, "history", "manifest.json")
DEFINITION = (
    "source and route: the earliest stored reading with a successful source_ok, from the collector "
    "files named in record_daily.json. backfill: the first date of each series in the backfill "
    "manifest, which is reported, not observed."
)


def _z(s):
    """Manifest firsts are 'YYYY-MM-DDTHH:MM:SSZ' or a bare date."""
    return s if "T" in s else s + "T00:00:00Z"


def build():
    rows = [r for r in rc.readings() if r["ok"]]
    first_route = {}
    for r in rows:
        if r["route"] and (r["route"] not in first_route or r["ts"] < first_route[r["route"]]):
            first_route[r["route"]] = r["ts"]
    reg = rc.Registry(rows)
    ms = []
    for sid, s in reg.sources.items():
        ms.append(("source", sid, rc.iso_z(s["first_ts"])))
    for route, ts in first_route.items():
        ms.append(("route", route, rc.iso_z(ts)))
    man = json.load(open(MANIFEST))
    for key, v in man["files"].items():
        ms.append(("backfill", key, _z(v["first"])))
    ms.sort(key=lambda m: (m[2], m[0], m[1]))
    return {
        "as_of_utc": rc.iso_z(rows[-1]["ts"]), "definition": DEFINITION,
        "milestones": [{"kind": k, "id": i, "first_utc": t, "first_day": t[:10]} for k, i, t in ms],
    }


def self_test(doc):
    rc.assert_no_nan(doc)
    m = doc["milestones"]
    assert m == sorted(m, key=lambda x: (x["first_utc"], x["kind"], x["id"])), "sorted by date"
    assert all(x["kind"] in ("source", "route", "backfill") and x["first_utc"][:10] == x["first_day"] for x in m)
    assert len({(x["kind"], x["id"]) for x in m}) == len(m), "no duplicates"
    assert {x["kind"] for x in m} == {"source", "route", "backfill"}
    assert all(x["first_day"] >= rc.START_DAY for x in m if x["kind"] != "backfill")
    print("record_milestones self-test ok: %d milestones" % len(m))


def main():
    doc = build()
    self_test(doc)
    if "--self-test" in sys.argv:
        return
    rc.write_json(OUT, doc)


if __name__ == "__main__":
    main()
