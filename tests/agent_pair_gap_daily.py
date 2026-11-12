"""BACKLOG 28a: daily gap history for flagged source pairs, on an inline fixture."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import pair_gap_daily as m


def main():
    a = {"2026-10-01T%02d" % h: 100.0 for h in range(3)}
    a.update({"2026-10-02T%02d" % h: 100.0 for h in range(2)})
    b = {"2026-10-01T%02d" % h: 110.0 for h in range(3)}
    b.update({"2026-10-02T%02d" % h: 120.0 for h in range(2)})
    g = m.daily_gaps(a, b)
    assert g["2026-10-01"] == (10.0, 3), g
    assert g["2026-10-02"] == (20.0, 2), g
    b["2026-10-02T05"] = 999.0                       # an hour a has no price for: must be skipped, not zero
    assert m.daily_gaps(a, b)["2026-10-02"] == (20.0, 2), "an hour missing from one side must not count as zero"
    rows = m.build([{"ccy": "XXX", "a": "s1", "b": "s2", "flag": True}], {"XXX": {"s1": a, "s2": b}})
    assert [r["day"] for r in rows] == ["2026-10-01", "2026-10-02"], rows
    assert rows[0]["median_gap_pct"] == 10.0 and rows[0]["hours"] == 3, rows[0]
    assert rows[1]["median_gap_pct"] == 20.0 and rows[1]["hours"] == 2, rows[1]
    assert m.build([{"ccy": "XXX", "a": "s1", "b": "s2", "flag": False}], {"XXX": {"s1": a, "s2": b}}) == []
    print("ok")


if __name__ == "__main__":
    main()
