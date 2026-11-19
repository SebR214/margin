"""SEB-468: the gap 30 and 90 days after a break is computed from fixture history only, a missing window is a gap, and the csv is well formed."""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import break_after as ba  # noqa: E402
import datetime as dt  # noqa: E402

days = [(dt.date(2019, 3, 1) + dt.timedelta(days=i)).isoformat() for i in range(150)]
off = {d: 20.0 for d in days}
street = {d: 20.0 * (1.5 if d < days[40] else 1.05) for d in days}       # 50% above, then 5% above from day 40
land = [
    {"event_id": "FIX-1", "ccy": "FIX", "event_date": days[0], "premium_before_pct": "50.0", "street_series": "fixture"},
    {"event_id": "FIX-2", "ccy": "FIX", "event_date": days[140], "premium_before_pct": "5.0", "street_series": "fixture"},
    {"event_id": "FIX-3", "ccy": "FIX", "event_date": days[0], "premium_before_pct": "none", "street_series": "none"},
]
rows = ba.build(land, {"FIX": street}, {"FIX": off})
assert [r["event_id"] for r in rows] == ["FIX-1", "FIX-2"], rows
assert rows[0]["gap_30d_pct"] == 50.0 and rows[0]["gap_90d_pct"] == 5.0, rows[0]
assert rows[1]["gap_30d_pct"] is None and rows[1]["gap_90d_pct"] is None, "a window past the data is a gap, not a guess"
assert all(r["label"] == "reported, not observed" and r["source"] for r in rows)
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "o.csv")
    ba.write(p, rows)
    got = list(csv.DictReader(open(p, newline="")))
    assert list(got[0]) == ba.FIELDS and got[1]["gap_30d_pct"] == "none" and got[0]["label"] == "reported, not observed", got
assert ba.selftest() == 0
print("agent_break_after: ok")
