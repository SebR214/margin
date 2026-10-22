#!/usr/bin/env python3
"""The event detector's four tests (SEB-311 step 3), on the stored history. Offline, no network, nothing written under data/.

  1. The same input gives the same events and numbers, every run, and judging the days in two sittings gives the rows of one.
  2. Sudan's looping official rate gives a data warning, not an event.
  3. A replay over everything stored (from the first day the official rate was stored, 10 Sep, to 21 Oct) flags Iraq's official step of
     9 Oct and the Bolivia street slide of 8 to 16 Sep, and flags none of the thin markets Brunei, Angola or Nepal.
  4. Every number in a record traces to stored rows: the official and street figures in each record are recomputed here from the raw
     CSV rows by a second, separate piece of code and must match. "Not enough evidence" is a result: Sudan's 13 Sep step, with 4 days of
     official history, is one.

    python3 tests/check_events.py
"""
import csv
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import detect_events as de  # noqa: E402

END = "2026-10-21"                      # the replay is cut here so later days cannot change what these tests assert
data = de.load()
start = de.first_day(data)

rows, recs = de.run_days(data, [], start, END)

# 1. the same rows every run; two sittings equal one
again, _ = de.run_days(data, [], start, END)
assert rows == again, "the same input gave different rows"
mid = de.day_add(start, 20)
first, _ = de.run_days(data, [], start, mid)
second, _ = de.run_days(data, first, de.day_add(mid, 1), END)
assert first + second == rows, "judging in two sittings gave other rows than one pass"

cands = [r for r in rows if r["status"] == "candidate"]
by = lambda ccy, kind, status: [r for r in rows if r["ccy"] == ccy and r["kind"] == kind and r["status"] == status]  # noqa: E731

# 2. Sudan
# A weekly repeat cannot be seen before the official rate has 8 days of readings, so a Sudan street slide on 16 Sep (7 days) is a real slide
# the detector had no way to call a loop; from the 17th on, the loop is visible and no Sudan event may appear
late = [r["event_id"] for r in cands if r["ccy"] == "SDG" and r["detected_on"] >= "2026-09-17"]
assert not late, "Sudan's looping official rate gave an event once the loop could be seen: %s" % late
warn = [r for r in rows if r["ccy"] == "SDG" and r["status"] == "data_warning"]
assert warn and all("flagged" in r["note"] or "loop" in r["note"] for r in warn), warn

# 3. the replay
iq = by("IQD", "official_break", "candidate")
assert len(iq) == 1 and "2026-10-07" <= iq[0]["detected_on"] <= "2026-10-11", iq
bo = by("BOB", "street_slide", "candidate")
assert len(bo) == 1 and "2026-09-08" <= bo[0]["detected_on"] <= "2026-09-17" and float(bo[0]["change_pct"]) < -10, bo
for thin in ("BND", "AOA", "NPR"):
    assert not [r for r in rows if r["ccy"] == thin and r["status"] in ("candidate", "data_warning")], "a thin market was flagged: " + thin
assert iq[0]["confirmation"] == "one source" and bo[0]["confirmation"] == "one source", "fx_live starts 21 Oct and OKX on 3 Oct: one source"

# 4. every number in a record traces to stored rows, recomputed from the raw files
fx = {}
for r in csv.DictReader(open(os.path.join(ROOT, "data", "fx_rates.csv"), newline="")):
    fx.setdefault((r["ccy"], r["ts_utc"][:10]), []).append((r["ts_utc"], r["fx_mid_per_usd"]))
st = {}
for r in csv.DictReader(open(os.path.join(ROOT, "data", "p2p_basis.csv"), newline="")):
    if r["source"] == "binance_p2p" and r["source_ok"] == "True" and r["buy_median"]:
        st.setdefault((r["ccy"], r["ts_utc"][:10]), []).append(float(r["buy_median"]))
assert recs, "no records"
for rid, rec in recs.items():
    if "trace" not in rec:
        continue
    for t in rec["trace"]:
        key = (t["ccy"], t["day"])
        if t["file"] == "data/fx_rates.csv":
            readings = sorted(fx.get(key, []))
            want = float(readings[-1][1]) if readings else None            # the last reading of the UTC day
        else:
            vals = st.get(key, [])
            want = statistics.median(vals) if len(vals) >= 12 else None
        side, name = t["number"].split(".")
        got = rec[side].get({"baseline": "baseline", "at_detection": "at_detection", "before": "before"}[name])
        assert got == want, "%s %s: the record says %s, the stored rows say %s" % (rid, t["number"], got, want)
# the timeline's points are stored numbers too
for rid, rec in recs.items():
    for pt in rec.get("timeline", []):
        readings = sorted(fx.get((rec["ccy"], pt["day"]), []))
        assert pt["official"] == (float(readings[-1][1]) if readings else None), (rid, pt)
        vals = st.get((rec["ccy"], pt["day"]), [])
        assert pt["street"] == (statistics.median(vals) if len(vals) >= 12 else None), (rid, pt)
assert any(len(rec.get("timeline", [])) >= 10 for rec in recs.values()), "a record needs its timeline"
assert any(r["status"] == "not_enough_evidence" for r in rows), "not enough evidence is a result and must appear"
sdg = [r for r in rows if r["ccy"] == "SDG" and r["status"] == "not_enough_evidence" and r["detected_on"] == "2026-09-13"]
assert sdg and "4 days of official history" in sdg[0]["note"], sdg

print("check_events: ok (%d rows: %d candidates, %d warnings; Iraq %s, Bolivia %s; Sudan a warning; thin markets quiet)" % (
    len(rows), len(cands), len(warn), iq[0]["detected_on"], bo[0]["detected_on"]))
