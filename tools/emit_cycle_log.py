#!/usr/bin/env python3
"""data/cycle_log.json: the last 48 hourly collection cycles, newest last, and the
clock the page header counts down.

Schema
    {
      "as_of_utc":        newest stored reading timestamp,
      "last_reading_utc": same (the newest counted reading),
      "cadence_seconds":  median gap between the last 24 cycles' newest reading stamps,
      "next_reading_utc": last_reading_utc + cadence_seconds,
      "definition":       how a cycle and its status are decided,
      "cycles": [  (up to 48, oldest first, newest last)
        {"hour_utc": "2026-10-05T05:00:00Z",   the UTC hour the cycle's readings fall in
         "status": "clean" | "source_missed" | "check_failed",
         "reasons": [source ids that missed that hour; "audit" or "audit:<family>" if a check failed],
         "readings": readings stored in that hour (record_common's definition),
         "last_reading_utc": newest reading stamp in that hour,
         "hours_since_previous": gap to the previous collected hour (1 = none missed),
         "partial_failures": {source id: failed rows} sources that answered but failed some rows}
      ],
      "steps": {   (the NEWEST cycle only)
        "hour_utc": ...,
        "currencies": {"collected": n, "of": 60},   currencies the index prices (published price), of its priced + withheld;
                                                    "with_a_reading" = any stored row this hour
        "routes":     {"priced": n, "of": 7},       routes with a samples.csv reading this hour
        "auditor":    {"rebuilt": drawn, "matched": passed, "sample_ts": ..., "same_hour": bool},
        "analyst":    null,                         the analyst has never run (SEB-238)
        "readings":   readings stored in that hour
      }
    }
A source "missed" an hour when it had answered before, the collector ran that hour,
and it has no successful row that hour (failed rows only, or no row). Rows that fail
while the source still answers for other currencies or sizes are routine (no ads on a
small board, a provider's size limit) and appear only as partial_failures.
check_failed wins over source_missed. Stored files only; no wall clock; stdlib only.

Usage: python3 tools/emit_cycle_log.py [--self-test]
"""

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

OUT = os.path.join(rc.DATA, "cycle_log.json")
N_CYCLES = 48
DEFINITION = (
    "A cycle is a UTC hour in which at least one reading was stored. Status is check_failed if the "
    "auditor's sample drawn in that hour had a failure; else source_missed if any source that had "
    "answered before has no successful row that hour; else clean. cadence_seconds is the median gap "
    "between the newest reading stamps of the last 24 cycles."
)


def _audit_rows():
    out = {}
    for r in rc.read_csv("audit_history.csv"):
        out[r["sample_ts"][:13]] = r
    return out


def build():
    rows = rc.readings()
    reg = rc.Registry(rows)
    hours = sorted(reg.all_hours)
    if not hours:
        raise SystemExit("no readings stored")
    last_ts = max(r["ts"] for r in rows if r["ok"])
    # per-hour tallies
    per = {}
    for r in rows:
        h = rc.hour_of(r["ts"])
        p = per.setdefault(h, dict(n=0, last=None, ok_src={}, fail_src={}, ccy=set(), route=set()))
        if r["ok"]:
            p["n"] += 1
            if p["last"] is None or r["ts"] > p["last"]:
                p["last"] = r["ts"]
            if r["file"] in ("basis.csv", "p2p_basis.csv") and r["ccy"]:
                p["ccy"].add(r["ccy"])
            if r["file"] == "samples.csv" and r["route"]:
                p["route"].add(r["route"])
        for sid, _ in r["sources"]:
            d = p["ok_src"] if r["ok"] else p["fail_src"]
            d[sid] = d.get(sid, 0) + 1
    audits = _audit_rows()
    latest = json.load(open(os.path.join(rc.DATA, "audit_latest.json")))
    latest_hour = latest["sample_ts"][:13]
    last_hours = hours[-N_CYCLES:]
    prev_of = {h: (hours[i - 1] if i else None) for i, h in enumerate(hours)}
    cycles = []
    for h in last_hours:
        p = per[h]
        missed = sorted(
            sid for sid, s in reg.sources.items()
            if s["cadence_hours"] == 1 and h >= rc.hour_of(s["first_ts"]) and sid not in p["ok_src"]
        )
        partial = {sid: n for sid, n in sorted(p["fail_src"].items()) if sid in p["ok_src"]}
        reasons = list(missed)
        failed_check = False
        a = audits.get(h)
        if a is not None and int(a["passed"]) < int(a["drawn"]):
            failed_check = True
            if h == latest_hour and latest.get("failures"):
                fams = sorted({f.get("family") for f in latest["failures"] if isinstance(f, dict) and f.get("family")})
                reasons += ["audit:" + x for x in fams] or ["audit"]
            else:
                reasons.append("audit")
        status = "check_failed" if failed_check else ("source_missed" if missed else "clean")
        gap = None
        if prev_of[h]:
            gap = int(round((rc._hour_dt(h) - rc._hour_dt(prev_of[h])).total_seconds() / 3600))
        cycles.append({
            "hour_utc": rc.hour_floor_iso(h), "status": status, "reasons": reasons,
            "readings": p["n"], "last_reading_utc": rc.iso_z(p["last"]) if p["last"] else None,
            "hours_since_previous": gap, "partial_failures": partial,
        })
    stamps = [dt.datetime.fromisoformat(per[h]["last"].replace("Z", "")).replace(tzinfo=None)
              if per[h]["last"].endswith("Z") else
              dt.datetime.fromisoformat(per[h]["last"]).astimezone(dt.timezone.utc).replace(tzinfo=None)
              for h in hours[-24:]]
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    cadence = int(round(rc.median(gaps))) if gaps else None
    last_dt = dt.datetime.fromisoformat(last_ts).astimezone(dt.timezone.utc).replace(tzinfo=None)
    nxt = (last_dt + dt.timedelta(seconds=cadence)).strftime("%Y-%m-%dT%H:%M:%SZ") if cadence else None
    idx = json.load(open(os.path.join(rc.DATA, "index_latest.json")))
    n_ccy = len(idx["countries"]) + len(idx["withheld"])
    n_routes = len({r["route"] for r in rows if r["file"] == "samples.csv" and r["route"]})
    nh = last_hours[-1]
    steps = {
        "hour_utc": rc.hour_floor_iso(nh),
        # ONE coverage measure site-wide: a currency counts as priced when the index publishes a price
        # for it (data/index_latest.json countries: at least 10 sellers, or a live exchange book).
        # "with_a_reading" is the looser count (any row stored this hour), kept for reference.
        "currencies": {"collected": len(idx["countries"]), "of": n_ccy, "with_a_reading": len(per[nh]["ccy"])},
        "routes": {"priced": len(per[nh]["route"]), "of": n_routes},
        "auditor": {"rebuilt": latest["drawn"], "matched": latest["passed"],
                    "sample_ts": rc.iso_z(latest["sample_ts"]), "same_hour": latest_hour == nh},
        "analyst": None,
        "readings": per[nh]["n"],
    }
    return {
        "as_of_utc": rc.iso_z(last_ts), "last_reading_utc": rc.iso_z(last_ts),
        "cadence_seconds": cadence, "next_reading_utc": nxt,
        "definition": DEFINITION, "cycles": cycles, "steps": steps,
    }


def self_test(doc):
    rc.assert_no_nan(doc)
    c = doc["cycles"]
    assert 1 <= len(c) <= N_CYCLES
    hrs = [x["hour_utc"] for x in c]
    assert hrs == sorted(hrs) and len(set(hrs)) == len(hrs), "newest last, no repeats"
    assert all(x["status"] in ("clean", "source_missed", "check_failed") for x in c)
    assert all((x["status"] == "clean") == (not x["reasons"]) for x in c), "reasons iff not clean"
    assert doc["steps"]["analyst"] is None
    assert doc["steps"]["hour_utc"] == hrs[-1]
    assert doc["steps"]["currencies"]["collected"] <= doc["steps"]["currencies"]["of"]
    assert doc["steps"]["routes"]["priced"] <= doc["steps"]["routes"]["of"]
    assert doc["steps"]["auditor"]["matched"] <= doc["steps"]["auditor"]["rebuilt"]
    assert doc["cadence_seconds"] and doc["cadence_seconds"] > 0
    assert doc["next_reading_utc"] > doc["last_reading_utc"]
    print("cycle_log self-test ok: %d cycles, newest %s, cadence %ss" % (len(c), hrs[-1], doc["cadence_seconds"]))


def main():
    doc = build()
    self_test(doc)
    if "--self-test" in sys.argv:
        return
    rc.write_json(OUT, doc)


if __name__ == "__main__":
    main()
