"""Research page 1, the live months (SEB-423 step 3). The yearly table (tools/research_capital_controls.py) is exchange history and ends
where the history files end. This piece appends what we saw ourselves: for each country, each month since we began, the typical daily
gap between the street price and the official rate, from data/index_hourly.csv (index_pct, one value per priced hour).

    day value   the median of that UTC day's hourly index_pct, a day needs 12 or more priced hours
    month value the median of its day values; "partial" when the month is not over (the newest day is before the month's last day)
    a month with fewer than 5 such days is left out, never filled

Nothing here feeds the index. Output (via run.py): data/research/capital_controls_months.json
    {"as_of_day": newest day in the hourly file, "label": "observed", "months": [{ccy, country, month, median_premium_pct, days, partial}]}
"""
import calendar
import csv
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
MIN_HOURS = 12
MIN_DAYS = 5


def month_rows(hourly, names=None):
    """hourly: iterable of (ccy, 'YYYY-MM-DDTHH...', value). Pure."""
    per = {}
    newest = ""
    for ccy, hour, v in hourly:
        per.setdefault(ccy, {}).setdefault(hour[:10], []).append(v)
        newest = max(newest, hour[:10])
    out = []
    for ccy in sorted(per):
        days = {d: st.median(v) for d, v in per[ccy].items() if len(v) >= MIN_HOURS}
        by_month = {}
        for d, v in days.items():
            by_month.setdefault(d[:7], []).append(v)
        for m in sorted(by_month):
            if len(by_month[m]) < MIN_DAYS:
                continue
            y, mo = int(m[:4]), int(m[5:7])
            last = "%s-%02d" % (m, calendar.monthrange(y, mo)[1])
            out.append({"ccy": ccy, "country": (names or {}).get(ccy, ccy), "month": m, "median_premium_pct": round(st.median(by_month[m]), 2),
                        "days": len(by_month[m]), "partial": newest < last})
    return out, newest


def read_hourly():
    with open(os.path.join(DATA, "index_hourly.csv"), newline="") as f:
        for r in csv.DictReader(f):
            try:
                v = float(r["index_pct"])
            except (TypeError, ValueError):
                continue
            if v == v:
                yield r["ccy"], r["hour_utc"], v


def build():
    names = {}
    for c in json.load(open(os.path.join(DATA, "heatmap_daily.json"))).get("currencies", []):
        names[c["ccy"]] = c.get("country") or c["ccy"]
    rows, newest = month_rows(read_hourly(), names)
    if not rows:
        sys.exit("capital_controls_months: no month had enough days")
    return {"as_of_day": newest, "label": "observed", "source": "data/index_hourly.csv, tools/research/capital_controls_months.py",
            "min_hours_a_day": MIN_HOURS, "min_days_a_month": MIN_DAYS, "countries": len({r["ccy"] for r in rows}), "months": rows}


def rebuild_yearly():
    """The yearly page re-runs from the history files, in the same pass."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import research_capital_controls as rcc
    rows, last = rcc.compute()
    rcc.write(rows, last)


def self_test():
    h = [("AAA", "2026-09-%02dT%02d:00:00+00:00" % (d, hr), 10.0 + (d if hr == 0 else 0)) for d in range(1, 8) for hr in range(14)]
    h += [("BBB", "2026-09-01T00:00:00+00:00", 1.0)]
    rows, newest = month_rows(h)
    assert newest == "2026-09-07" and len(rows) == 1, rows
    r = rows[0]
    assert r["ccy"] == "AAA" and r["days"] == 7 and r["partial"] is True and r["median_premium_pct"] == 10.0, r
    print("capital_controls_months self-test ok")
