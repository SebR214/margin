#!/usr/bin/env python3
"""data/home_facts.json: the facts the home page's changing sentences are made from (SEB-423 step 1). Plain code, no model.

    largest_move   the ranked country whose gap to the official rate (data/index_hourly.csv, index_pct) moved most in the 24 hours
                   up to the newest hour (against the last reading at most 3 hours before the 24 hour mark), in points; the direction; and since when the gap has sat above or below its own typical
                   level (the median of the last 30 days of hourly values). null when no country moved more than 1 point.
    what_changed   up to 8 items from the last 7 days, newest first, each {date, kind, link, ...numbers}:
        crossed_up / crossed_down  a ranked country's daily gap (data/heatmap_daily.json) crossed 5% from one day to the next
        event                      an event on data/events_published.json whose date is in the window
        source_added               a source whose first row (data/source_registry.json) is in the window; "status" says approved or quarantine
        finding_changed            a finding on data/finding_status.json whose newest retest status (data/finding_tests.csv) differs from
                                   the one before it, dated in the window
        route_flip                 the stablecoin went from cheaper than the cheapest app to dearer or back, by the majority of a day's
                                   hours at the amount with the most hours (data/routes_hourly.json)

Numbers only, no prose: the words are copy.json's (homeData). Nothing is read from the wall clock: the window ends on the newest hour
in data/index_hourly.csv. Every number is checked against its source file by tools/audit_claims.py (types home_largest_move and
home_what_changed) before js/home.js shows a sentence.

    python3 tools/emit_home_facts.py [--self-test]
"""
import bisect
import csv
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "home_facts.json")

MIN_MOVE_PTS = 1.0
MEDIAN_DAYS = 30
WINDOW_DAYS = 7
MAX_ITEMS = 8
CROSS_PCT = 5.0
PREV_SLACK = dt.timedelta(hours=3)   # the reading 24 hours back may be up to 3 hours older when that hour has no row
MIN_DAY_HOURS = 12


def jload(name, default=None):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def parse_hour(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def read_index_hourly():
    """{ccy: [(datetime, index_pct), ...]} sorted by time. A country with no price in an hour has no row."""
    by = {}
    with open(os.path.join(DATA, "index_hourly.csv"), newline="") as f:
        for r in csv.DictReader(f):
            try:
                v = float(r["index_pct"])
            except (TypeError, ValueError):
                continue
            if v != v:
                continue
            by.setdefault(r["ccy"], []).append((parse_hour(r["hour_utc"]), v))
    for rows in by.values():
        rows.sort()
    return by


def ranked_names():
    """{ccy: country name} for countries that are ranked: priced this hour and not on a frozen official rate."""
    out = {}
    for c in (jload("index_latest.json", {}) or {}).get("countries", []):
        if c.get("index_pct") is not None and c.get("denominator_class") != "unmaintained":
            out[c["ccy"]] = c.get("country") or c["ccy"]
    return out


def largest_move(by, names, newest):
    prev = newest - dt.timedelta(hours=24)
    best = None
    for ccy, rows in by.items():
        if ccy not in names:
            continue
        times = [t for t, _ in rows]
        i_now = bisect.bisect_left(times, newest)
        i_prev = bisect.bisect_right(times, prev) - 1
        if i_now >= len(times) or times[i_now] != newest or i_prev < 0 or prev - times[i_prev] > PREV_SLACK:
            continue
        delta = rows[i_now][1] - rows[i_prev][1]
        if best is None or abs(delta) > abs(best[1]):
            best = (ccy, delta, i_now, times[i_prev])
    if best is None or abs(best[1]) <= MIN_MOVE_PTS:
        return None
    ccy, delta, i_now, prev = best
    rows = by[ccy]
    lo = newest - dt.timedelta(days=MEDIAN_DAYS)
    win = [(t, v) for t, v in rows if lo <= t <= newest]
    med = statistics.median(v for _, v in win)
    now_v = rows[i_now][1]
    side = 1 if now_v > med else -1 if now_v < med else 0
    since, whole = None, False
    if side:
        k = len(win) - 1
        while k >= 0 and ((win[k][1] > med) - (win[k][1] < med)) == side:
            k -= 1
        whole = k < 0
        since = win[k + 1][0].date().isoformat()
    return {"ccy": ccy, "country": names[ccy], "points": round(abs(delta), 1), "direction": "dearer" if delta > 0 else "cheaper",
            "now_pct": round(now_v, 1), "typical_pct": round(med, 1), "side": "above" if side > 0 else "below" if side < 0 else "at",
            "since": since, "since_whole_window": whole, "from_hour": prev.isoformat(), "to_hour": newest.isoformat()}


def crossings(names, start):
    h = jload("heatmap_daily.json", {}) or {}
    days = h.get("days", [])
    out = []
    for c in h.get("currencies", []):
        if c["ccy"] not in names or c.get("ranked") is False:
            continue
        cells = c.get("cells", [])
        for i in range(1, len(days)):
            if days[i] < start or i >= len(cells):
                continue
            a, b = cells[i - 1], cells[i]
            if a is None or b is None:
                continue
            if a < CROSS_PCT <= b or a >= CROSS_PCT > b:
                out.append({"date": days[i], "kind": "crossed_up" if b >= CROSS_PCT else "crossed_down", "ccy": c["ccy"],
                            "country": names[c["ccy"]], "pct": round(b, 1), "link": "country.html?ccy=" + c["ccy"]})
    return out


def events(start):
    pub = jload("events_published.json", {}) or {}
    out = []
    for e in pub.get("events", []):
        if e["date"] >= start:
            out.append({"date": e["date"], "kind": "event", "id": e["id"], "ccy": e["ccy"], "event_kind": e["event_kind"],
                        "pct": round(abs(float(e["change_pct"])), 1), "link": "event.html?id=" + e["id"]})
    return out


def sources(start):
    out = []
    for name, s in ((jload("source_registry.json", {}) or {}).get("sources", {})).items():
        if s.get("first_row", "") >= start:
            out.append({"date": s["first_row"], "kind": "source_added", "source": name, "status": s.get("status"), "link": "sources.html"})
    return out


def findings(start):
    status = (jload("finding_status.json", {}) or {}).get("findings", {})
    rows = {}
    p = os.path.join(DATA, "finding_tests.csv")
    if status and os.path.exists(p):
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                if r["finding_id"] in status and r["status"] in ("holds", "weaker", "no_longer_true"):
                    rows.setdefault(r["finding_id"], []).append((r["ts_utc"], r["status"]))
    out = []
    for fid, rs in rows.items():
        rs.sort()
        daily = {}
        for ts, st in rs:
            daily[ts[:10]] = st
        days = sorted(daily)
        for a, b in zip(days, days[1:]):
            if daily[a] != daily[b] and b >= start:
                out.append({"date": b, "kind": "finding_changed", "id": fid, "from": daily[a], "to": daily[b], "link": "finding.html?id=" + fid})
    return out


def route_flips(start):
    h = jload("routes_hourly.json", {}) or {}
    cols = h.get("hour_columns", [])
    if "stable_cheaper" not in cols:
        return []
    ih, ic = cols.index("hour_utc"), cols.index("stable_cheaper")
    out = []
    for r in h.get("routes", []):
        amounts = r.get("amounts", [])
        if not amounts:
            continue
        a = max(amounts, key=lambda x: len(x["hours"]))
        per = {}
        for row in a["hours"]:
            per.setdefault(row[ih][:10], []).append(bool(row[ic]))
        days = sorted(d for d, v in per.items() if len(v) >= MIN_DAY_HOURS)
        state = {d: sum(per[d]) * 2 > len(per[d]) for d in days}
        flip = None
        for d0, d1 in zip(days, days[1:]):
            if (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days == 1 and state[d0] != state[d1] and d1 >= start:
                flip = {"date": d1, "kind": "route_flip", "route": r["id"], "amount": a["amount"], "now": "cheaper" if state[d1] else "dearer",
                        "link": "sending-money.html"}
        if flip:
            out.append(flip)
    return out


def build():
    by = read_index_hourly()
    newest = max(rows[-1][0] for rows in by.values())
    names = ranked_names()
    start = (newest - dt.timedelta(days=WINDOW_DAYS)).date().isoformat()
    items = crossings(names, start) + events(start) + sources(start) + findings(start) + route_flips(start)
    items.sort(key=lambda x: (x["date"], x["kind"], x.get("ccy") or x.get("source") or x.get("route") or x.get("id") or ""), reverse=True)
    return {"as_of_utc": newest.isoformat(), "window_start": start, "window_days": WINDOW_DAYS,
            "largest_move": largest_move(by, names, newest), "what_changed": items[:MAX_ITEMS], "what_changed_total": len(items)}


def self_test():
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    rows = [(t0 + dt.timedelta(hours=h), 10.0 if h < 600 else 14.0) for h in range(721)]
    rows = [(t, v + (6 if t == t0 + dt.timedelta(hours=720) else 0)) for t, v in rows]
    by = {"AAA": rows, "BBB": [(t, 3.0) for t, _ in rows]}
    m = largest_move(by, {"AAA": "Aland", "BBB": "Bland"}, rows[-1][0])
    assert m and m["ccy"] == "AAA" and m["points"] == 6.0 and m["direction"] == "dearer" and m["side"] == "above", m
    assert m["since"] == (t0 + dt.timedelta(hours=600)).date().isoformat(), m
    assert largest_move({"BBB": by["BBB"]}, {"BBB": "Bland"}, rows[-1][0]) is None
    print("self-test ok")
    return 0


def main():
    doc = build()
    new = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    old = open(OUT).read() if os.path.exists(OUT) else ""
    if new != old:
        with open(OUT, "w") as f:
            f.write(new)
    m = doc["largest_move"]
    print("home facts as of %s: largest move %s; %d of %d changes listed" % (
        doc["as_of_utc"], "%s %s %.1f points" % (m["ccy"], m["direction"], m["points"]) if m else "none above 1 point",
        len(doc["what_changed"]), doc["what_changed_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
