"""BACKLOG 27a: near-miss report for countries with no price, on an inline fixture."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import no_price_near_miss as m


def main():
    rows = [{"ts_utc": "2026-01-01T0%d:30:00+00:00" % i, "ccy": "AAA", "n_buy": "5", "n_sell": str(n)}
            for i, n in enumerate((3, 8, 10, 12))]
    doc = m.build(["AAA", "BBB"], rows, 10, "2026-01-01T04:00:00+00:00")
    a = doc["currencies"]["AAA"]
    assert a["median_ads"] == 9, a
    assert a["hours_at_or_above"] == 2, a
    assert a["threshold"] == 10 and a["status"] == "near miss", a
    assert doc["currencies"]["BBB"]["status"] == "no data", doc
    low = [{"ts_utc": "2026-01-01T0%d:30:00+00:00" % i, "ccy": "CCC", "n_sell": "4"} for i in range(3)]
    assert m.build(["CCC"], low, 10, "2026-01-01T04:00:00+00:00")["currencies"]["CCC"]["status"] == "far"
    print("ok")


if __name__ == "__main__":
    main()
