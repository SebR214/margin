"""SEB-467: the two findings that stopped retesting are retested again. Fixed rows only, no live data."""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import retest_findings as rf

ROOT = rf.ROOT
T0 = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)


def row(ccy, hours, ratio):
    return {"ts": T0 + dt.timedelta(hours=hours), "ccy": ccy, "ratio": ratio}


def test_spike_outcomes():
    rows = [
        row("AAA", 0, 1.0), row("AAA", 1, 2.5), row("AAA", 2, 1.5),             # starts at 1, closes at 2: closed
        row("BBB", 0, 1.0), row("BBB", 1, 3.0), row("BBB", 2, 2.9), row("BBB", 3, 2.8), row("BBB", 4, 2.7), row("BBB", 5, 1.0),  # open past 3 h: judged, not closed
        row("CCC", 0, 1.0), row("CCC", 1, 4.0), row("CCC", 2, 3.0),              # not closed, not 3 h old: not judged
        row("DDD", 0, 2.2), row("DDD", 1, 2.4), row("DDD", 2, 1.0),              # first row is already a spike, the next one is the same spike
        row("EEE", 0, None), row("EEE", 1, 5.0), row("EEE", 5, 5.0),             # rows without a ratio are ignored; a row 4 h later is judging enough
    ]
    got = sorted((c, round((s - T0).total_seconds() / 3600), k) for c, s, k in rf.spike_outcomes(rows))
    assert got == [("AAA", 1, True), ("BBB", 1, False), ("DDD", 0, True), ("EEE", 1, False)], got


def test_spread_metric_on_fixture():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "data"))
        end = T0 + dt.timedelta(days=40)
        with open(os.path.join(d, "data", "p2p_spread_signal.csv"), "w") as f:
            f.write("ts_utc,ccy,spread_pct,ccy_mean_spread_pct,spread_ratio,n_prior_readings\n")
            for i in range(12):                   # twelve currencies, each one spike that closes after an hour, all inside the last 28 days
                c = "C%02d" % i
                for h, v in ((0, 1.0), (1, 3.0), (2, 1.0)):
                    f.write("%s,%s,1,1,%s,5\n" % ((end - dt.timedelta(days=10) + dt.timedelta(hours=h)).isoformat(), c, v))
            f.write("%s,OLD,1,1,3.0,5\n%s,OLD,1,1,3.0,5\n" % ((end - dt.timedelta(days=35)).isoformat(), (end - dt.timedelta(days=35) + dt.timedelta(hours=5)).isoformat()))
            f.write("%s,LAST,1,1,1.0,5\n" % end.isoformat())
        json.dump({"as_of_utc": end.isoformat(), "findings": [{"id": "p2p_spread_signal", "last_recheck_utc": end.isoformat(), "headline": {}}]},
                  open(os.path.join(d, "data", "findings.json"), "w"))
        test = json.load(open(os.path.join(ROOT, "findings_tests", "p2p_spread_signal.json")))
        res = rf.m_spread(d, test, end, None)
        assert "invalid" not in res and res["n_obs"] == 12 and res["value"] == 1.0, res         # the 35-day-old spike is outside the window
        assert rf.classify(res["value"], test) == "holds"
        stale = rf.m_spread(d, test, end + dt.timedelta(days=4), None)
        assert "3 days" in stale["invalid"], stale
        # too few spikes: not tested fairly
        open(os.path.join(d, "data", "p2p_spread_signal.csv"), "w").write("ts_utc,ccy,spread_pct,ccy_mean_spread_pct,spread_ratio,n_prior_readings\n%s,A,1,1,3.0,5\n" % end.isoformat())
        assert "fewer than 10" in rf.m_spread(d, test, end, None)["invalid"]


def test_volume_fires_on_a_new_headline_day():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "data"))
        json.dump({"status": "ok", "reconstruction_max_error_bps": 0.01, "n_samples": 2000, "tier_schedule_as_of": "2026-11-01T10:39:41Z"},
                  open(os.path.join(d, "data", "volume_crossover.json"), "w"))
        def put(day):
            json.dump({"as_of_utc": day + "T08:00:00Z", "findings": [{"id": "volume_crossover", "last_recheck_utc": day + "T08:00:00Z",
                                                                      "headline": {"value": 1000.0, "as_of_utc": day + "T08:00:00Z"}}]},
                      open(os.path.join(d, "data", "findings.json"), "w"))
        test = {}
        put("2026-11-10")
        a = rf.m_volume(d, test, T0, None)
        put("2026-11-11")
        b = rf.m_volume(d, test, T0, None)
        assert a["data_through"] != b["data_through"], (a, b)       # the fee table did not change, the day did
        last = {"ts_utc": "2026-11-10T09:00:00+00:00", "data_through": a["data_through"]}
        assert rf.triggered("volume_crossover", b, last, "2026-11-11")
        assert not rf.triggered("volume_crossover", a, last, "2026-11-11")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("agent_stale_findings: ok")
