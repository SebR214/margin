#!/usr/bin/env python3
"""A broken official rate never counts as a stress trigger in the retest (SEB-301, ROADMAP step 3).

12 of the 13 stored SDG triggers come from er-api's broken Sudan rate (looping, jumping, lagging; see data/official_rate_flags.csv).
This feeds tools/retest_findings.m_stress a temp repo with 12 SDG triggers whose street price moved a lot, and checks:

  SDG flagged in the official-rate flags     -> none survive, all 12 counted as skipped
  the same triggers with no flag             -> all survive (the control: the street move is real, only the flag removes them)
  a flagged currency next to a clean one     -> only the clean one survives
and that on the stored data no flagged currency survives.

    python3 tests/check_stress_retest.py
"""
import csv
import datetime as dt
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import retest_findings as rf  # noqa: E402

TEST = {"evidence_file": "data/stress_signal.csv"}
DAY0 = dt.date(2026, 10, 1)


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def build(root, ccys, flagged):
    """12 triggers per currency, street buy price +10% on each trigger day."""
    trig, basis = [], []
    for c in ccys:
        for i in range(1, 13):
            d = DAY0 + dt.timedelta(days=2 * i)
            trig.append([d.isoformat() + "T00:00:00+00:00", c, "30", "6", "0.1", d.isoformat(), ""])
            for day, px in ((d - dt.timedelta(days=1), 100.0), (d, 110.0)):
                basis.append([day.isoformat() + "T12:00:00Z", c, "binance_p2p", "True", px])
    write(os.path.join(root, "data", "stress_signal.csv"),
          ["ts_utc", "ccy", "index_pct", "gap_widened_pt", "official_move_pct", "triggered_on", "note"], trig)
    write(os.path.join(root, "data", "p2p_basis.csv"), ["ts_utc", "ccy", "source", "source_ok", "buy_median"], basis)
    write(os.path.join(root, "data", "official_rate_flags.csv"), ["as_of_date", "ccy", "rule", "detail"],
          [["2026-10-24", c, "weekly_loop", "test"] for c in flagged])


def run(ccys, flagged):
    with tempfile.TemporaryDirectory() as d:
        build(d, ccys, flagged)
        res = rf.m_stress(d, TEST, None, None)
    assert "invalid" not in res, res
    return res, json.loads(res["detail"])


def main():
    res, det = run(["SDG"], ["SDG"])
    assert res["value"] == 0 and det["survived"] == [] and det["skipped_flagged_official_rate"] == 12, (res, det)
    res, det = run(["SDG"], [])
    assert res["value"] == 1 and len(det["survived"]) == 12 and det["skipped_flagged_official_rate"] == 0, (res, det)
    res, det = run(["SDG", "IQD"], ["SDG"])
    assert {k[0] for k in det["survived"]} == {"IQD"} and det["skipped_currencies"] == ["SDG"], det
    assert abs(res["value"] - 0.5) < 1e-9, res

    # stored data: whatever is flagged today must have no surviving trigger
    flags = {r["ccy"] for r in rf.rows_of(os.path.join(ROOT, "data", "official_rate_flags.csv"))}
    trig = rf.rows_of(os.path.join(ROOT, "data", "stress_signal.csv"))
    surv, skipped, _, _ = rf.stress_survivors(trig, flags, {})
    assert surv == [] and len(skipped) == sum(1 for t in trig if t["ccy"] in flags), (surv, skipped)
    print("stress retest: a broken official rate never survives (ok)")


if __name__ == "__main__":
    main()
