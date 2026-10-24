#!/usr/bin/env python3
"""Does a street premium come before an official step? (SEB-384 step 2.) Plain code, stored files only, no model.

Reads the exchange history in data/history/ (reported, not observed), the official series the rules v4 replay uses, and the
rules v4 events (data/history/events_reported_rules4.csv). Writes two files and prints the tables that go on SEB-384. SEB-384 names them data/backtest_*.csv; they carry the history
label, which the isolation check allows only under data/history/, so they live there:

    data/history/backtest_watch.csv     one row per currency per month start
    data/history/backtest_landing.csv   one row per confirmed official break in the replay

Month start: the first day of the month (up to the 7th) on which both a street price and an official rate exist. Skipped when there
is none. Premium: (street price of one USDT / official rate - 1) * 100, the street price the median of the exchange series of that day
(a series is a venue's own USDT or USDC close; a venue quoted the other way round is turned over once, by which way it sits nearer the
official rate; for Argentina the reported blue-dollar mid is a series as well). months_above_5 is the run of consecutive months, this
one included, with a premium above 5%.

Step: the rules v4 detector's official break, the official rate going UP (more local money per dollar) by 10% or more: a candidate
row of events_reported_rules4.csv with change_pct of 10 or more, or a "further official break of X%" update row with X of 10 or more
(the detector's 30-day rule folds a second step into the open event). A row marked data_warning or not_enough_evidence is not a step.
hit_12m is 1 when a step falls after the month start and within 12 months of it, 0 when none did, and blank (open) when the 12 months
have not all passed, or the official series ends before them. hit_6m the same for 6 months.

Landing: for each official break the replay confirmed with two sources and a move up, the official rate 14 to 21 days after the break
(median of the days) over the street price 7 to 14 days before it (median of the days).

Kill rule, fixed before the tables were read (SEB-384): for managed currencies, the 12-month hit rate of the 10% and over premium
bands together must be at least twice that of the under-2% band, at least 10 points higher, and rest on at least 30 resolved month
starts over at least 3 currencies. If not, the watch (step 3) is not built.

Own prices (data/backtest_watch_ours.csv, outside data/history/ because they are observed): from 10 Aug 2026 the premium is the one each country published in data/index_hourly.csv, median of the day. Those rows are labelled "ours". None of them has 6 months behind it yet.

Usage:  python3 tools/backtest_watch.py              # writes both files, prints the tables
        python3 tools/backtest_watch.py --selftest   # rules on fixtures, no files
"""
import csv
import datetime as dt
import glob
import math
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
HIST = os.path.join(ROOT, "data", "history")
OUT_WATCH = os.path.join(HIST, "backtest_watch.csv")
OUT_LAND = os.path.join(HIST, "backtest_landing.csv")
OUT_OURS = os.path.join(ROOT, "data", "backtest_watch_ours.csv")      # our own prices are observed, not history, so they stay out of data/history/
EVENTS = os.path.join(HIST, "events_reported_rules4.csv")
INDEX_HOURLY = os.path.join(ROOT, "data", "index_hourly.csv")
LABEL_HIST = "reported, not observed"
LABEL_OURS = "ours"
OWN_START = "2026-08-10"
STEP_PCT = 10.0
BANDS = [("under 2%", -1e9, 2.0), ("2 to 5%", 2.0, 5.0), ("5 to 10%", 5.0, 10.0), ("10 to 25%", 10.0, 25.0), ("over 25%", 25.0, 1e9)]
HIGH_BANDS = ("10 to 25%", "over 25%")
KILL_FACTOR, KILL_POINTS, KILL_MIN_N, KILL_MIN_CCY = 2.0, 10.0, 30, 3
WATCH_FIELDS = ["month_start", "ccy", "type", "premium_pct", "band", "months_above_5", "street_series", "official", "hit_12m", "hit_6m",
                "first_step_date", "first_step_pct", "label", "source"]
LAND_FIELDS = ["event_id", "ccy", "type", "event_date", "official_move_pct", "confirmation", "kind", "street_before", "official_after", "landing_ratio",
               "premium_before_pct", "street_series", "label", "source"]
FURTHER = re.compile(r"further official break of (-?[0-9.]+)%")


def band_of(p):
    for name, lo, hi in BANDS:
        if lo <= p < hi:
            return name
    return BANDS[-1][0]


def add_months(day, n):
    d = dt.date.fromisoformat(day)
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(d.day, last)).isoformat()


def month_next(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return "%04d-%02d" % (y + m // 12, m % 12 + 1)


def steps_from(events_path=EVENTS):
    """{ccy: sorted [(date, pct)]}: the official steps up of STEP_PCT or more."""
    out = {}
    with open(events_path, newline="") as f:
        for r in csv.DictReader(f):
            pct = None
            if r["status"] == "candidate" and r["kind"] == "official_break":
                try:
                    pct = float(r["change_pct"])
                except ValueError:
                    pct = None
            elif r["status"] == "update":                      # a further official step is noted on whichever open event it fell in
                m = FURTHER.search(r["note"])
                pct = float(m.group(1)) if m else None
            if pct is not None and pct >= STEP_PCT:
                out.setdefault(r["ccy"], {})[r["as_of_date"]] = max(pct, out.get(r["ccy"], {}).get(r["as_of_date"], 0))
    return {c: sorted(d.items()) for c, d in out.items()}


def confirmed_breaks(events_path=EVENTS):
    """The official breaks the landing table covers, moving up: [(event_id, ccy, date, pct, confirmation, kind)].
    Every break the replay confirmed with two sources (any size), and every break of STEP_PCT or more whatever its confirmation (a central
    bank series alone is "one source"), the second step folded into an open event included (kind "further", pct the further step)."""
    out, seen = [], set()
    with open(events_path, newline="") as f:
        for r in csv.DictReader(f):
            kind, pct = None, None
            if r["status"] == "candidate" and r["kind"] == "official_break":
                try:
                    kind, pct = "event", float(r["change_pct"])
                except ValueError:
                    continue
            elif r["status"] == "update":
                m = FURTHER.search(r["note"])
                if m:
                    kind, pct = "further", float(m.group(1))
            if kind is None or pct <= 0 or (r["ccy"], r["as_of_date"]) in seen:
                continue
            if r["confirmation"] == "two sources" or pct >= STEP_PCT:
                seen.add((r["ccy"], r["as_of_date"]))
                out.append((r["event_id"] if kind == "event" else r["event_id"] + "+further", r["ccy"], r["as_of_date"], pct, r["confirmation"], kind))
    return out


def hit(steps, start, months, last_official):
    """1 / 0 / None (open). A step must fall after start and on or before start + months."""
    end = add_months(start, months)
    if end > last_official:
        return None, None
    for d, p in steps:
        if start < d <= end:
            return 1, (d, p)
    return 0, None


def orient(series, off):
    """Turn a venue's series over when 1/price sits nearer the official rate than price does. {day: price}."""
    a, b = [], []
    for d, v in series.items():
        o = off.get(d)
        if o and v > 0:
            a.append(abs(math.log(v / o)))
            b.append(abs(math.log(1.0 / v / o)))
    if len(a) < 10:
        return None
    return series if st.median(a) <= st.median(b) else {d: 1.0 / v for d, v in series.items() if v > 0}


def narrow_venues(tracked):
    """{ccy: {venue: {day: close}}} from the single-venue daily candle files (USDT or USDC pairs only)."""
    out = {}
    wide = ("binance_spot", "bitso_wide", "kraken", "buda", "coingecko")
    for p in sorted(glob.glob(os.path.join(HIST, "candles_*_1d.csv"))):
        name = os.path.basename(p)[len("candles_"):-len("_1d.csv")]
        if " " in name or name in wide:
            continue
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                pair = r["pair"].upper()
                if "USDT" not in pair and "USDC" not in pair:
                    continue
                try:
                    v = float(r["close"])
                except ValueError:
                    continue
                if v > 0 and r["ccy"] in tracked:
                    out.setdefault(r["ccy"], {}).setdefault(name, {})[r["ts_utc"][:10]] = v
    return out


def parallel_blue():
    out = {}
    p = os.path.join(HIST, "parallel_dollar_daily.csv")
    if os.path.exists(p):
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                if r["market"] == "blue":
                    try:
                        b, s = float(r["buy"]), float(r["sell"])
                    except ValueError:
                        continue
                    if b > 0 and s > 0:
                        out[r["date"][:10]] = (b + s) / 2
    return out


def street_by_day(data, bh):
    """{ccy: {day: (median price, series names)}} and {ccy: [series names]} over every series the history files hold."""
    off = data["off"]
    series = {}
    for venue, per in bh.street_series().items():
        for c, d in per.items():
            series.setdefault(c, {})[venue] = d
    for c, per in narrow_venues(set(off)).items():
        for v, d in per.items():
            series.setdefault(c, {})[v] = d
    blue = parallel_blue()
    if blue and "ARS" in off:
        series.setdefault("ARS", {})["Argentina blue dollar (reported mid)"] = blue
    out, names = {}, {}
    for c, per in series.items():
        if c not in off:
            continue
        used = {}
        for v, d in per.items():
            o = orient(d, off[c])
            if o:
                used[v] = o
        names[c] = sorted(used)
        days = {}
        for v, d in used.items():
            for day, p in d.items():
                days.setdefault(day, []).append((v, p))
        out[c] = {day: (st.median(p for _, p in vs), sorted(v for v, _ in vs)) for day, vs in days.items()}
    return out, names


def month_starts(street, off):
    """{ccy: [(month_start_day, premium_pct, series)]}"""
    res = {}
    for c, sd in street.items():
        o = off.get(c, {})
        months = sorted({d[:7] for d in sd})
        rows = []
        for ym in months:
            for k in range(1, 8):
                day = "%s-%02d" % (ym, k)
                if day in sd and day in o:
                    p, who = sd[day]
                    rows.append((day, (p / o[day] - 1) * 100, who))
                    break
        res[c] = rows
    return res


def own_rows(off):
    """Month starts from our own record: {ccy: [(day, premium_pct)]}, the first day of each month (from OWN_START) with a reading."""
    if not os.path.exists(INDEX_HOURLY):
        return {}
    per = {}
    with open(INDEX_HOURLY, newline="") as f:
        for r in csv.DictReader(f):
            if r["hour_utc"][:10] < OWN_START:                  # one row per country and hour, the number it published
                continue
            try:
                per.setdefault(r["ccy"], {}).setdefault(r["hour_utc"][:10], []).append(float(r["index_pct"]))
            except ValueError:
                continue
    out = {}
    for c, days in per.items():
        seen = {}
        for d in sorted(days):
            seen.setdefault(d[:7], (d, st.median(days[d])))
        out[c] = list(seen.values())
    return out


def build(data, bh, steps):
    off, managed = data["off"], data["managed"]
    last_official = max(d for v in off.values() for d in v)
    street, names = street_by_day(data, bh)
    rows = []
    for c, ms in sorted(month_starts(street, off).items()):
        typ = "managed" if c in managed else "floating"
        run, prev = 0, None
        for day, prem, who in ms:
            ym = day[:7]
            run = (run + 1 if prev and month_next(prev) == ym else 1) if prem > 5 else 0
            prev = ym
            s = steps.get(c, [])
            h12, st12 = hit(s, day, 12, last_official)
            h6, _ = hit(s, day, 6, last_official)
            rows.append({"month_start": day, "ccy": c, "type": typ, "premium_pct": round(prem, 3), "band": band_of(prem), "months_above_5": run,
                         "street_series": "; ".join(who), "official": "BIS, Frankfurter v2 or fawazahmed0 daily series, data/history/",
                         "hit_12m": "" if h12 is None else h12, "hit_6m": "" if h6 is None else h6,
                         "first_step_date": st12[0] if st12 else "", "first_step_pct": st12[1] if st12 else "", "label": LABEL_HIST,
                         "source": "tools/backtest_watch.py over data/history/ candles and official series; steps from events_reported_rules4.csv"})
    for c, ms in sorted(own_rows(off).items()):
        typ = "managed" if c in managed else "floating"
        run, prev = 0, None
        for day, prem in ms:
            ym = day[:7]
            run = (run + 1 if prev and month_next(prev) == ym else 1) if prem > 5 else 0
            prev = ym
            rows.append({"month_start": day, "ccy": c, "type": typ, "premium_pct": round(prem, 3), "band": band_of(prem), "months_above_5": run,
                         "street_series": "published figure, data/index_hourly.csv", "official": "open.er-api, data/fx_rates.csv",
                         "hit_12m": "", "hit_6m": "", "first_step_date": "", "first_step_pct": "", "label": LABEL_OURS,
                         "source": "tools/backtest_watch.py over data/index_hourly.csv (observed)"})
    return rows, street, names


def landing(data, street, events_path=EVENTS):
    off, managed = data["off"], data["managed"]
    rows = []
    for eid, c, day, pct, conf, kind in confirmed_breaks(events_path):
        sd, o = street.get(c, {}), off.get(c, {})

        d0 = dt.date.fromisoformat(day)

        def window(series, a, b, pick=lambda v: v):
            lo, hi = (d0 + dt.timedelta(days=a)).isoformat(), (d0 + dt.timedelta(days=b)).isoformat()
            vals = [pick(v) for dd, v in series.items() if lo <= dd <= hi]
            return st.median(vals) if vals else None
        before = window(sd, -14, -7, lambda v: v[0])
        after = window(o, 14, 21)
        lo, hi = (d0 - dt.timedelta(days=14)).isoformat(), (d0 - dt.timedelta(days=7)).isoformat()
        near = [(dd, v) for dd, v in sd.items() if lo <= dd <= hi]
        who = sorted({n for _, (_, ns) in near for n in ns})
        off_before = window(o, -14, -7)
        rows.append({"event_id": eid, "ccy": c, "type": "managed" if c in managed else "floating", "event_date": day, "official_move_pct": pct, "confirmation": conf, "kind": kind,
                     "street_before": "" if before is None else round(before, 6), "official_after": "" if after is None else round(after, 6),
                     "landing_ratio": "" if before is None or after is None else round(after / before, 4),
                     "premium_before_pct": "" if before is None or not off_before else round((before / off_before - 1) * 100, 2),
                     "street_series": "; ".join(who), "label": LABEL_HIST,
                     "source": "tools/backtest_watch.py over data/history/ candles and official series; events_reported_rules4.csv"})
    return rows


def hit_table(rows):
    """[(type, band, n12, hits12, n6, hits6, ccys12)] over resolved history rows."""
    out = []
    for typ in ("managed", "floating"):
        for name, _, _ in BANDS:
            sel = [r for r in rows if r["type"] == typ and r["band"] == name and r["label"] == LABEL_HIST]
            r12 = [r for r in sel if r["hit_12m"] != ""]
            r6 = [r for r in sel if r["hit_6m"] != ""]
            out.append((typ, name, len(r12), sum(r["hit_12m"] for r in r12), len(r6), sum(r["hit_6m"] for r in r6), len({r["ccy"] for r in r12}),
                        len({r["ccy"] for r in r12 if r["hit_12m"] == 1})))
    return out


def kill_rule(table):
    """(passes, why) for managed currencies: the 12-month rate in the 10%+ bands against the under-2% band."""
    low = next(t for t in table if t[0] == "managed" and t[1] == "under 2%")
    hi = [t for t in table if t[0] == "managed" and t[1] in HIGH_BANDS]
    n_hi, h_hi = sum(t[2] for t in hi), sum(t[3] for t in hi)
    ccys_hi = max((t[6] for t in hi), default=0)          # a lower bound on the currencies in the two bands together
    if low[2] == 0 or n_hi == 0:
        return False, "no resolved month starts in the low or the high band"
    r_lo, r_hi = low[3] / low[2] * 100, h_hi / n_hi * 100
    ok = r_hi >= KILL_FACTOR * r_lo and r_hi - r_lo >= KILL_POINTS and n_hi >= KILL_MIN_N and ccys_hi >= KILL_MIN_CCY
    return ok, ("10%%+ bands: %d of %d month starts (%.1f%%), at least %d currencies; under 2%%: %d of %d (%.1f%%). Needs at least %gx, "
                "%g points more, %d month starts, %d currencies." % (h_hi, n_hi, r_hi, ccys_hi, low[3], low[2], r_lo, KILL_FACTOR, KILL_POINTS,
                                                                        KILL_MIN_N, KILL_MIN_CCY))


def write(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:                                          # a history row has no empty field: "open" for an outcome not yet known, "none" where a figure does not apply
            w.writerow({k: ("open" if v == "" and k.startswith("hit_") else "none" if v == "" else v) for k, v in r.items()})


def pct(a, b):
    return "%.1f%%" % (100.0 * a / b) if b else "n/a"


def print_tables(rows, land, table):
    print("\nHit rate by premium band (a step of 10%% or more in the official rate, after the month start). History rows only, %d.\n" %
          sum(1 for r in rows if r["label"] == LABEL_HIST))
    print("| type | premium band | month starts (12m resolved) | stepped within 12m | hit rate 12m | month starts (6m resolved) | stepped within 6m | hit rate 6m | currencies | currencies that stepped |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for typ, name, n12, h12, n6, h6, nc, nh in table:
        print("| %s | %s | %d | %d | %s | %d | %d | %s | %d | %d |" % (typ, name, n12, h12, pct(h12, n12), n6, h6, pct(h6, n6), nc, nh))
    print("\nLanding ratio: official rate 14 to 21 days after / street price 7 to 14 days before. Every break up that the replay confirmed with two sources, and every one of 10%% or more: %d.\n" % len(land))
    print("| date | currency | type | official move | confirmed by | premium before | street before | official after | landing ratio |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(land, key=lambda r: (r["event_date"], r["ccy"])):
        print("| %s | %s | %s | +%.1f%% | %s | %s | %s | %s | %s |" % (r["event_date"], r["ccy"], r["type"], r["official_move_pct"], r["confirmation"],
              "%s%%" % r["premium_before_pct"] if r["premium_before_pct"] != "" else "no street price", r["street_before"] or "-",
              r["official_after"] or "-", r["landing_ratio"] if r["landing_ratio"] != "" else "-"))
    for name, sel in (("all", land), ("moves of 10%% or more", [r for r in land if r["official_move_pct"] >= STEP_PCT])):
        ratios = [r["landing_ratio"] for r in sel if r["landing_ratio"] != ""]
        if ratios:
            print("\nLanding ratios, %s: found for %d of %d; median %.3f, lowest %.3f, highest %.3f." % (name % (), len(ratios), len(sel), st.median(ratios), min(ratios), max(ratios)))


def main():
    import backfill_history as bh
    data, _, _ = bh.history_data()
    steps = steps_from()
    rows, street, names = build(data, bh, steps)
    land = landing(data, street)
    write(OUT_WATCH, WATCH_FIELDS, [r for r in rows if r["label"] == LABEL_HIST])
    write(OUT_OURS, WATCH_FIELDS, [r for r in rows if r["label"] == LABEL_OURS])
    write(OUT_LAND, LAND_FIELDS, land)
    table = hit_table(rows)
    print_tables(rows, land, table)
    ok, why = kill_rule(table)
    print("\nKill rule: %s. %s" % ("PASSES, step 3 is built" if ok else "FAILS, step 3 is not built", why))
    print("\nwrote %s (%d rows), %s (%d rows), %s (%d rows)" % (os.path.relpath(OUT_WATCH, ROOT), sum(1 for r in rows if r["label"] == LABEL_HIST),
                                                                         os.path.relpath(OUT_LAND, ROOT), len(land), os.path.relpath(OUT_OURS, ROOT), sum(1 for r in rows if r["label"] == LABEL_OURS)))
    return 0


def selftest():
    assert band_of(-3) == "under 2%" and band_of(2) == "2 to 5%" and band_of(4.99) == "2 to 5%" and band_of(5) == "5 to 10%"
    assert band_of(10) == "10 to 25%" and band_of(25) == "over 25%" and band_of(900) == "over 25%"
    assert add_months("2020-01-31", 1) == "2020-02-29" and add_months("2020-12-01", 12) == "2021-12-01" and add_months("2021-03-31", 6) == "2021-09-30"
    assert month_next("2020-12") == "2021-01" and month_next("2020-02") == "2020-03"
    s = [("2021-03-10", 15.0)]
    assert hit(s, "2021-01-01", 12, "2022-06-01") == (1, ("2021-03-10", 15.0))
    assert hit(s, "2021-03-10", 12, "2022-06-01") == (0, None), "a step on the month start day is not after it"
    assert hit(s, "2020-01-01", 12, "2022-06-01") == (0, None) and hit(s, "2020-01-01", 6, "2022-06-01") == (0, None)
    assert hit(s, "2021-01-01", 6, "2022-06-01")[0] == 1 and hit(s, "2022-01-01", 12, "2022-06-01") == (None, None), "open until 12 months have passed"
    off = {"2020-01-%02d" % d: 10.0 for d in range(1, 29)}
    up = {d: 1.0 / 10.0 for d in off}                      # a venue quoted the other way round: 0.1 coins per... turned over to 10
    assert orient(up, off) == {d: 10.0 for d in off}, "turned over"
    assert orient({d: 10.5 for d in off}, off) == {d: 10.5 for d in off}
    assert orient({"2020-01-01": 10.0}, off) is None, "too few days to judge"
    ok = [("managed", "under 2%", 100, 5, 100, 3, 10, 4), ("managed", "10 to 25%", 20, 8, 20, 6, 4, 3), ("managed", "over 25%", 15, 9, 15, 7, 3, 3)]
    tab = [("managed", b, 0, 0, 0, 0, 0, 0) for b in ("2 to 5%", "5 to 10%")] + ok
    assert kill_rule(tab)[0] is True, kill_rule(tab)
    flat = [("managed", "under 2%", 100, 20, 100, 15, 10, 8), ("managed", "10 to 25%", 20, 5, 20, 4, 4, 3), ("managed", "over 25%", 15, 4, 15, 3, 3, 2)]
    assert kill_rule(flat)[0] is False
    thin = [("managed", "under 2%", 100, 5, 100, 3, 10, 4), ("managed", "10 to 25%", 4, 4, 4, 4, 2, 2)]
    assert kill_rule(thin)[0] is False, "too few month starts and currencies"
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "e.csv")
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["as_of_date", "event_id", "ccy", "kind", "status", "confirmation", "detected_on", "baseline", "latest", "change_pct", "note"])
            w.writerow(["2021-01-05", "A1", "TRY", "official_break", "candidate", "two sources", "", "", "", "12.5", ""])
            w.writerow(["2021-01-05", "A2", "TRY", "official_break", "candidate", "one source", "", "", "", "8", ""])
            w.writerow(["2021-01-12", "A1", "TRY", "official_break", "update", "two sources", "", "", "", "30", "week 1 after: a further official break of 11.5% inside"])
            w.writerow(["2021-01-19", "A1", "TRY", "official_break", "update", "two sources", "", "", "", "30", "week 2 after: a further official break of 4% inside"])
            w.writerow(["2021-02-01", "B1", "EGP", "official_break", "data_warning", "none", "", "", "", "40", "a unit error"])
            w.writerow(["2021-02-02", "B2", "EGP", "official_break", "candidate", "two sources", "", "", "", "-20", ""])
        assert steps_from(p) == {"TRY": [("2021-01-05", 12.5), ("2021-01-12", 11.5)]}, steps_from(p)
        assert confirmed_breaks(p) == [("A1", "TRY", "2021-01-05", 12.5, "two sources", "event"), ("A1+further", "TRY", "2021-01-12", 11.5, "two sources", "further"),
                                    ("A1+further", "TRY", "2021-01-19", 4.0, "two sources", "further")], confirmed_breaks(p)
    print("backtest_watch self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
