#!/usr/bin/env python3
"""data/map_timeline/: the dollar map at any day since 2000, precomputed (SEB-384 step 4). Stored files only, no model.

The home grid shows, per country, the gap between the real dollar price and the official rate. This writes that figure for every
day the files hold, so the page only reads a file and recolours (no computing in the browser):

    data/map_timeline/index.json        the countries, the years, the classes, where our own record starts
    data/map_timeline/<year>.json       2000 to this year: one value and one class per country per day
    data/map_timeline/last90.json       the last 90 days, one value per country per hour, from our own record
    data/map_timeline/landing.json      where the official rate landed after each past break of 10% or more with a street price before it

Every point has a class, a one-character code, and the page labels it on the grid:
  0 "ours"               our own published figure (data/heatmap_daily.json for a day, data/index_hourly.csv for an hour), from 10 Aug 2026.
                         A day or hour we did not read stays empty: never filled, never carried over.
  1 "reported exchange"  (street price of one USDT on an exchange, from data/history/) / official rate - 1, in percent, from 1 Jan 2014.
                         Reported by the exchanges, not seen by us. The street price is the median of the exchange series of that day.
  2 "official only"      no street price for that day: the official rate's move over the 30 days to that day, in percent (positive: the
                         local money got weaker). From the official series in data/history/ (BIS back to 2000). Not a premium.
  -                      no data; the value is null.
Values are tenths of a percent as whole numbers (123 is 12.3%). The official rate behind a history day is its last reading on or before
that day, up to 3 days back (the central bank series has weekdays only); a day with none is empty. 'ours' never reads a history file and
the history never feeds an index, a price or the unbroken-hours count: this file is read by the home page's time control only.

Idempotent: no wall clock, the same inputs give the same bytes.

Usage:  python3 tools/emit_map_timeline.py              # writes data/map_timeline/
        python3 tools/emit_map_timeline.py --selftest   # rules on fixtures, writes nothing
"""
import csv
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT_DIR = os.path.join(ROOT, "data", "map_timeline")
HEAT = os.path.join(ROOT, "data", "heatmap_daily.json")
INDEX_HOURLY = os.path.join(ROOT, "data", "index_hourly.csv")
FIRST_YEAR = 2000
MENU_MIN = 10   # a year is in the menu when at least this many countries have a price in it
EXCHANGE_FROM = "2014-01-01"
OFFICIAL_LAG_DAYS = 3
MOVE_DAYS = 30
HOURLY_DAYS = 90
LANDING = os.path.join(ROOT, "data", "history", "backtest_landing.csv")
LANDING_MIN_MOVE = 10.0
CLASSES = {"0": "ours", "1": "reported exchange", "2": "official only"}


def tenths(x):
    return int(round(x * 10))


def day_range(a, b):
    d, end = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def last_on_or_before(series, sorted_days, day, lag=OFFICIAL_LAG_DAYS):
    """The (day, value) of the newest reading on or before day, at most lag days back; None otherwise."""
    import bisect
    i = bisect.bisect_right(sorted_days, day) - 1
    if i < 0:
        return None
    d = sorted_days[i]
    if (dt.date.fromisoformat(day) - dt.date.fromisoformat(d)).days > lag:
        return None
    return d, series[d]


def point(day, off, off_days, street, own):
    """(value in tenths or None, class code) for one country and day. own is the published figure of that day, or None; it counts only
    from the day our record starts (the caller passes own_start)."""
    if own is not None:
        return tenths(own), "0"
    o = last_on_or_before(off, off_days, day)
    if o is None:
        return None, "-"
    if street is not None and day >= EXCHANGE_FROM:
        return tenths((street / o[1] - 1) * 100), "1"
    prev = last_on_or_before(off, off_days, (dt.date.fromisoformat(day) - dt.timedelta(days=MOVE_DAYS)).isoformat())
    if prev is None:
        return None, "-"
    return tenths((o[1] / prev[1] - 1) * 100), "2"


def build_year(year, ccys, off, street, own, own_start, last_day):
    """{'year', 'days', 'ccy': {CCY: {'v': [...], 'k': '...'}}} for one year, to last_day at most."""
    a, b = "%d-01-01" % year, min("%d-12-31" % year, last_day)
    days = list(day_range(a, b))
    res = {}
    off_days = {c: sorted(off.get(c, {})) for c in ccys}
    for c in ccys:
        v, k = [], []
        for d in days:
            ov = own.get(c, {}).get(d) if d >= own_start else None
            pv, pk = point(d, off.get(c, {}), off_days[c], street.get(c, {}).get(d), ov)
            if d >= own_start and ov is None:
                pv, pk = None, "-"                               # from our first day on, only what we read: a gap stays a gap
            v.append(pv)
            k.append(pk)
        res[c] = {"v": v, "k": "".join(k)}
    return {"year": year, "days": days, "ccy": res}


def hourly(ccys, rows, last_hour):
    """The last HOURLY_DAYS days, hour by hour, from index_hourly rows [(hour_iso, ccy, pct)]. A country's list starts at its first hour."""
    end = dt.datetime.fromisoformat(last_hour)
    hours = [(end - dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H") for h in range(HOURLY_DAYS * 24 - 1, -1, -1)]
    pos = {h: i for i, h in enumerate(hours)}
    per = {}
    for h, c, p in rows:
        if h[:13] in pos and c in ccys:
            per.setdefault(c, {})[pos[h[:13]]] = tenths(p)
    res = {}
    for c in ccys:
        got = per.get(c)
        if not got:
            continue
        lo, hi = min(got), max(got)
        res[c] = {"o": lo, "v": [got.get(i) for i in range(lo, hi + 1)]}
    return {"hours": hours, "classes": {"0": CLASSES["0"]}, "ccy": res}


def load_ours():
    """({ccy: {day: pct}}, first_day, last_day) from data/heatmap_daily.json, our published daily figure."""
    h = json.load(open(HEAT))
    own = {}
    for c in h["currencies"]:
        for d, v in zip(h["days"], c["cells"]):
            if v is not None:
                own.setdefault(c["ccy"], {})[d] = v
    return own, h["first_day"], h["last_day"], [{"ccy": c["ccy"], "country": c["country"], "class": c.get("class", ""), "ranked": c.get("ranked", True)} for c in h["currencies"]]


def load_hourly_rows():
    rows = []
    with open(INDEX_HOURLY, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["hour_utc"][:13], r["ccy"], float(r["index_pct"])))
            except ValueError:
                continue
    return rows


def landing(path, names):
    """The breaks of LANDING_MIN_MOVE or more that have a landing ratio (tools/backtest_watch.py), newest first.
    ratio = official rate 14 to 21 days after / street price 7 to 14 days before."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                move, ratio = float(r["official_move_pct"]), float(r["landing_ratio"])
                prem = float(r["premium_before_pct"])
            except ValueError:
                continue                                   # "none": no street price around that break
            if move >= LANDING_MIN_MOVE:
                out.append({"ccy": r["ccy"], "country": names.get(r["ccy"], r["ccy"]), "date": r["event_date"], "move_pct": round(move, 1),
                            "premium_before_pct": round(prem, 1), "landing_ratio": round(ratio, 4)})
    return sorted(out, key=lambda x: (x["date"], x["ccy"]), reverse=True)


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")


def main():
    import backfill_history as bh
    import backtest_watch as bw
    own, own_start, last_day, countries = load_ours()
    ccys = [c["ccy"] for c in countries]
    data, _, _ = bh.history_data()
    street_med, _ = bw.street_by_day(data, bh)
    street = {c: {d: p for d, (p, _) in per.items()} for c, per in street_med.items()}
    os.makedirs(OUT_DIR, exist_ok=True)
    years = list(range(FIRST_YEAR, int(last_day[:4]) + 1))
    menu = []
    for y in years:
        yr = build_year(y, ccys, data["off"], street, own, own_start, last_day)
        dump(os.path.join(OUT_DIR, "%d.json" % y), yr)
        # the year menu lists only years where at least MENU_MIN countries have a price, ours or reported (25 Oct, Seb):
        # earlier years were almost all empty squares. Their files stay, so a slider window can still reach back.
        if sum(1 for x in yr["ccy"].values() if "0" in x["k"] or "1" in x["k"]) >= MENU_MIN:
            menu.append(y)
    rows = load_hourly_rows()
    last_hour = max(r[0] for r in rows) + ":00"
    dump(os.path.join(OUT_DIR, "last90.json"), hourly(set(ccys), rows, last_hour))
    dump(os.path.join(OUT_DIR, "landing.json"), {"rows": landing(LANDING, {c["ccy"]: c["country"] for c in countries}),
                                                  "note": "reported, not seen by us: street prices and official rates from data/history/"})
    dump(os.path.join(OUT_DIR, "index.json"), {
        "classes": CLASSES, "years": years, "menu_years": menu, "menu_min": MENU_MIN, "first_day": "%d-01-01" % FIRST_YEAR, "last_day": last_day, "own_start": own_start,
        "exchange_from": EXCHANGE_FROM, "last_hour": last_hour, "hourly_days": HOURLY_DAYS, "countries": countries,
        "units": "tenths of a percent", "note": "class 1 and 2 are reported, not seen by us; class 2 is the official rate's 30 day move, not a premium"})
    print("map_timeline: %d countries, %d to %s, hourly to %s, own record from %s" % (len(ccys), FIRST_YEAR, last_day, last_hour, own_start))
    return 0


def selftest():
    assert tenths(12.34) == 123 and tenths(-0.04) == 0 and tenths(118.72) == 1187
    off = {"2020-01-02": 10.0, "2020-01-03": 10.0, "2020-02-03": 11.0}
    od = sorted(off)
    assert last_on_or_before(off, od, "2020-01-05") == ("2020-01-03", 10.0), "a weekend takes the last reading"
    assert last_on_or_before(off, od, "2020-01-07") is None, "more than 3 days back is empty"
    assert last_on_or_before(off, od, "2019-12-31") is None
    assert point("2020-01-03", off, od, 10.5, None) == (50, "1"), "reported exchange: street / official - 1"
    assert point("2020-01-03", off, od, None, None) == (None, "-"), "no reading 30 days back: empty"
    assert point("2020-02-03", off, od, None, None) == (100, "2"), "official only: 30 day move, 11 against 10"
    assert point("2013-12-31", {"2013-12-31": 10.0, "2013-12-01": 5.0}, ["2013-12-01", "2013-12-31"], 20.0, None) == (1000, "2"), "street before 2014 is not used"
    assert point("2026-09-01", off, od, 11.0, 4.5) == (45, "0"), "our own figure wins"
    y = build_year(2020, ["AAA"], {"AAA": off}, {"AAA": {"2020-01-03": 10.5}}, {}, "2026-08-10", "2020-02-05")
    assert len(y["days"]) == 36 and y["days"][0] == "2020-01-01" and y["days"][-1] == "2020-02-05"
    a = y["ccy"]["AAA"]
    assert len(a["v"]) == len(a["k"]) == 36 and a["v"][0] is None and a["k"][0] == "-"
    assert a["v"][2] == 50 and a["k"][2] == "1" and a["k"][33] == "2" and a["v"][33] == 100, (a["v"][33], a["k"][33])
    y = build_year(2026, ["AAA"], {"AAA": {"2026-08-11": 3.0}}, {"AAA": {"2026-08-11": 3.3, "2026-08-12": 3.3}}, {"AAA": {"2026-08-11": 7.7}}, "2026-08-10", "2026-08-12")
    assert y["ccy"]["AAA"]["k"][-3:] == "-0-" or y["ccy"]["AAA"]["k"][-2:] == "0-", y["ccy"]["AAA"]["k"]
    assert y["ccy"]["AAA"]["v"][-2] == 77 and y["ccy"]["AAA"]["v"][-1] is None, "from our first day only what we read"
    hr = hourly({"AAA", "BBB"}, [("2026-10-24T06", "AAA", 1.25), ("2026-10-24T07", "AAA", -0.5), ("2020-01-01T00", "AAA", 9.0), ("2026-10-24T07", "ZZZ", 2.0)],
                "2026-10-24T07:00")
    assert len(hr["hours"]) == 2160 and hr["hours"][-1] == "2026-10-24T07" and set(hr["ccy"]) == {"AAA"}
    assert hr["ccy"]["AAA"]["v"] == [12, -5] and hr["ccy"]["AAA"]["o"] == 2158, hr["ccy"]["AAA"]
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "l.csv")
        with open(p, "w", newline="") as f:
            f.write("event_id,ccy,type,event_date,official_move_pct,confirmation,kind,street_before,official_after,landing_ratio,premium_before_pct,street_series,label,source\n")
            f.write("a,ARS,managed,2015-12-18,38.6117,one source,event,15.0,13.6,0.9078,54.43,x,l,s\n")
            f.write("b,TRY,floating,2018-08-10,14.2304,two sources,event,4.85,6.35,1.3107,-1.17,x,l,s\n")
            f.write("c,MXN,floating,2020-02-28,3.63,two sources,event,none,23.3,none,none,x,l,s\n")
            f.write("d,EGP,floating,2024-03-07,60.3576,two sources,event,none,46.8,none,none,x,l,s\n")
            f.write("e,TRY,floating,2020-08-06,3.8367,two sources,event,6.9,7.35,1.0651,0.16,x,l,s\n")
        got = landing(p, {"ARS": "Argentina", "TRY": "Turkey"})
        assert [(x["ccy"], x["date"], x["landing_ratio"], x["premium_before_pct"]) for x in got] == [("TRY", "2018-08-10", 1.3107, -1.2), ("ARS", "2015-12-18", 0.9078, 54.4)], got
    print("emit_map_timeline self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
