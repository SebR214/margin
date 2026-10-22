#!/usr/bin/env python3
"""The currency event detector, shadow mode (SEB-311 step 3). Plain code, no model, publishes nothing.

Reads stored CSVs, writes two things, both append-only:

    data/events.csv               one row per candidate, update, closing or data warning
    data/event_records/<id>.json  the record behind each event: baseline, street before, official lag, offers and depth,
                                  the after, the checks run on each source, and where every number came from

What is an event (ROADMAP.md "What counts as an event"):
  official_break  the official rate (er-api, data/fx_rates.csv, the last reading of each UTC day) is 3% or more away from its value
                  3 days earlier
  street_slide    the street price (the Binance board's buy price, data/p2p_basis.csv, the day's median) is 10% or more away from its
                  value 7 days earlier, in a market with 10 or more ads on each side (data/p2p_depth.csv, or p2p_sides.csv where depth
                  was not stored yet)
Not an event: a thin market; a slow drift that never crosses the line; anything caused by our own source breaking. A currency whose
official rate is flagged (the rules of tools/check_official_rates.py, run on the data up to that day: a weekly loop, a jump that
reverses, 30 days unchanged, a lag behind the live rate) or whose official rate steps to a value it had a week or two earlier
(a loop seen before 28 days of history exist) is never an event: it writes a data_warning row saying what would have fired.
A currency with fewer than 14 days of official history cannot be judged for an official break (a weekly repeat could not be seen), or fewer
than 7 for a street slide: not_enough_evidence.

Confirmed only when two official sources show the step (er-api and data/fx_live.csv, which starts 21 Oct) or two street sources move
10% or more the same way over the window (Binance and OKX, data/p2p_okx.csv, which starts 3 Oct). Otherwise the row says "one source".

Reopened every 7 days for 8 weeks (an update row and a new entry in the record's "after"), then closed. Nothing earlier is rewritten:
a record file only gains entries. An event is not raised again for the same currency and kind for 14 days.

The detector works one UTC day at a time, using only data up to and including that day, so a replay over history and the daily run
give the same rows. The daily run catches up from the last day in events.csv to yesterday. Never reads the wall clock for a number.

    python3 tools/detect_events.py                 # catch up to yesterday, append to data/events.csv and data/event_records/
    python3 tools/detect_events.py --replay        # every day since the data began, in memory; prints the list, writes nothing
    python3 tools/detect_events.py --self-test
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import check_official_rates as cor  # noqa: E402

DATA = os.path.join(HERE, "data")
EVENTS = os.path.join(DATA, "events.csv")
RECORDS = os.path.join(DATA, "event_records")
FIELDS = ["as_of_date", "event_id", "ccy", "kind", "status", "confirmation", "detected_on", "baseline", "latest", "change_pct", "note"]

OFFICIAL_STEP_PCT = 3.0
OFFICIAL_DAYS = 3
STREET_SLIDE_PCT = 10.0
STREET_DAYS = 7
MIN_ADS = 10
MIN_OFFICIAL_HISTORY = 14      # days of official readings needed to judge an official break: two weeks, so a weekly repeat can be seen
MIN_STREET_HISTORY = 7         # and to judge a street slide: one week of the official rate to compare it with
MIN_READINGS = 12              # hourly readings that make a street day count
REARM_DAYS = 14
UPDATE_EVERY = 7
CLOSE_AFTER = 56
LOOP_TOL_PCT = 2.0             # a value within 2% of one seen 7 or 14 days before


def day_add(d, n):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()


def med(xs):
    return statistics.median(xs) if xs else None


def pct(a, b):
    return round((b / a - 1) * 100, 4)


# ------------------------------------------------------------------ the stored series, read once

def read(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def load(root_read=read):
    """Everything the detector uses, as day-keyed dictionaries. Nothing here knows today's date."""
    off = cor.daily(cor.FX, "ts_utc", "fx_mid_per_usd")                       # {ccy: {day: last reading}}
    live = cor.daily(cor.LIVE, "ts_utc", "rate_per_usd", ok_col="source_ok")
    n_off = {}
    for r in root_read("fx_rates.csv"):
        n_off[(r["ccy"], r["ts_utc"][:10])] = n_off.get((r["ccy"], r["ts_utc"][:10]), 0) + 1
    street = {"binance_p2p": {}, "okx_p2p": {}}
    for name in ("p2p_basis.csv", "p2p_okx.csv"):
        for r in root_read(name):
            src = r["source"]
            if src not in street or r["source_ok"] != "True" or not r["buy_median"]:
                continue
            k = (r["ccy"], r["ts_utc"][:10])
            street[src].setdefault(k, []).append(float(r["buy_median"]))
    street = {s: {k: med(v) for k, v in d.items() if len(v) >= MIN_READINGS} for s, d in street.items()}
    sizes = {}
    for r in root_read("p2p_sides.csv"):                                          # capped at 10: "10 or more" and nothing past it
        if r["n_buy"] == "" or r["n_sell"] == "":
            continue                                                               # an unreadable count is a gap, not a zero
        sizes.setdefault((r["ccy"], r["ts_utc"][:10]), {"b": [], "s": []})
        sizes[(r["ccy"], r["ts_utc"][:10])]["b"].append(float(r["n_buy"]))
        sizes[(r["ccy"], r["ts_utc"][:10])]["s"].append(float(r["n_sell"]))
    depth = {}
    for r in root_read("p2p_depth.csv"):
        if r["buy_total"] == "" or r["sell_total"] == "":
            continue
        k = (r["ccy"], r["ts_utc"][:10])
        depth.setdefault(k, {"b": [], "s": []})
        depth[k]["b"].append(float(r["buy_total"]))
        depth[k]["s"].append(float(r["sell_total"]))
    size = {}
    for k in set(sizes) | set(depth):
        src = depth.get(k) or sizes.get(k)                                         # depth where stored, else the capped counts
        size[k] = (med(src["b"]), med(src["s"]), "p2p_depth.csv" if k in depth else "p2p_sides.csv")
    street_c = {s: {} for s in street}
    for s, d in street.items():
        for (ccy, day), v in d.items():
            street_c[s].setdefault(ccy, {})[day] = v
    return {"off": off, "n_off": n_off, "live": live, "street": street, "street_c": street_c, "size": size}


def cut(series, as_of):
    """{day: v} limited to days up to and including as_of."""
    return {d: v for d, v in series.items() if d <= as_of}


# ------------------------------------------------------------------ the rules

def loop_repeat(off, d):
    """True when the official value on day d is within 2% of its value 7 or 14 days earlier: the step is last week's again."""
    v = off.get(d)
    for n in (7, 14):
        p = off.get(day_add(d, -n))
        if v and p and abs(v / p - 1) * 100 <= LOOP_TOL_PCT:
            return n
    return None


def official_step(off, d):
    a, b = off.get(day_add(d, -OFFICIAL_DAYS)), off.get(d)
    if not a or not b:
        return None
    ch = pct(a, b)
    return ch if abs(ch) >= OFFICIAL_STEP_PCT else None


def street_slide(s, d):
    a, b = s.get(day_add(d, -STREET_DAYS)), s.get(d)
    if not a or not b:
        return None
    ch = pct(a, b)
    return ch if abs(ch) >= STREET_SLIDE_PCT else None


def thick(size, ccy, d):
    """The market's ads on each side over the 7 days to d: both medians at least MIN_ADS. Returns (ok, buy, sell, source) or None."""
    b, s, src = [], [], set()
    for n in range(STREET_DAYS + 1):
        x = size.get((ccy, day_add(d, -n)))
        if x:
            b.append(x[0])
            s.append(x[1])
            src.add(x[2])
    if not b:
        return None
    mb, ms = med(b), med(s)
    return (mb >= MIN_ADS and ms >= MIN_ADS), mb, ms, "+".join(sorted(src))


def flags_as_of(D, off, live):
    """The rules of tools/check_official_rates.py on the series up to D: {ccy: [rule names]}."""
    series = {c: cut(v, D) for c, v in off.items()}
    lv = {c: cut(v, D) for c, v in live.items()}
    out = {}
    for _, ccy, rule, _ in cor.check({c: v for c, v in series.items() if v}, lv):
        if rule == "flat_30":
            continue            # a rate that has not moved for 30 days is a peg, information for a person: the day it breaks is what this is for
        out.setdefault(ccy, []).append(rule)
    return out


# ------------------------------------------------------------------ one day

def event_id(ccy, kind, d):
    return "%s-%s-%s" % (ccy, kind, d)


def confirmation(kind, data, ccy, d, ch):
    """(text, sources shown). Two sources or 'one source'."""
    if kind == "official_break":
        live = cut(data["live"].get(ccy, {}), d)
        a, b = live.get(day_add(d, -OFFICIAL_DAYS)), live.get(d)
        if a and b and abs(pct(a, b)) >= OFFICIAL_STEP_PCT and (pct(a, b) > 0) == (ch > 0):
            return "two sources", ["er-api", "fx_live"]
        return "one source", ["er-api"]
    okx = data["street"]["okx_p2p"].get
    a, b = okx((ccy, day_add(d, -STREET_DAYS))), okx((ccy, d))
    if a and b and abs(pct(a, b)) >= STREET_SLIDE_PCT and (pct(a, b) > 0) == (ch > 0):
        return "two sources", ["binance_p2p", "okx_p2p"]
    return "one source", ["binance_p2p"]


def street_view(data, ccy, d):
    return data["street"]["binance_p2p"].get((ccy, d))


def build_record(data, ccy, kind, d, ch, conf, sources, ok_size, flagged):
    off = data["off"].get(ccy, {})
    sb = data["street"]["binance_p2p"]
    base_day = day_add(d, -(OFFICIAL_DAYS if kind == "official_break" else STREET_DAYS))
    rec = {"id": event_id(ccy, kind, d), "ccy": ccy, "kind": kind, "detected_on": d, "confirmation": conf, "sources_showing_it": sources,
           "rules": {"official_step_pct": OFFICIAL_STEP_PCT, "official_days": OFFICIAL_DAYS, "street_slide_pct": STREET_SLIDE_PCT,
                     "street_days": STREET_DAYS, "min_ads_each_side": MIN_ADS}}
    rec["official"] = {"source": "er-api, data/fx_rates.csv, last reading of each UTC day", "baseline_day": day_add(d, -OFFICIAL_DAYS),
                       "baseline": off.get(day_add(d, -OFFICIAL_DAYS)), "at_detection": off.get(d)}
    if rec["official"]["baseline"] and rec["official"]["at_detection"]:
        rec["official"]["change_pct"] = pct(rec["official"]["baseline"], rec["official"]["at_detection"])
    s0, s1 = sb.get((ccy, day_add(d, -STREET_DAYS))), sb.get((ccy, d))
    rec["street"] = {"source": "binance_p2p buy price, data/p2p_basis.csv, median of the UTC day", "before_day": day_add(d, -STREET_DAYS),
                     "before": s0, "at_detection_day": d, "at_detection": s1}
    if s0 and s1:
        rec["street"]["change_pct"] = pct(s0, s1)
    # how long the official source took: the first day the street had moved 3% from its price 3 days earlier, in the official step's
    # direction, up to the detection day; for a street slide, the days until the official rate is 3% from its value 7 days earlier
    rec["official_lag_days"] = None
    if kind == "official_break":
        for n in range(OFFICIAL_DAYS * 3, -1, -1):
            x = day_add(d, -n)
            a, b = sb.get((ccy, day_add(x, -OFFICIAL_DAYS))), sb.get((ccy, x))
            if a and b and abs(pct(a, b)) >= OFFICIAL_STEP_PCT and (pct(a, b) > 0) == (ch > 0):
                rec["official_lag_days"] = n
                rec["official_lag_note"] = "the street price was already %s%% from 3 days before on %s; the official rate crossed %s%% on %s" % (
                    pct(a, b), x, OFFICIAL_STEP_PCT, d)
                break
        if rec["official_lag_days"] is None:
            rec["official_lag_note"] = "the street price had not moved 3% in the same direction in the 9 days before the official step"
    else:
        rec["official_lag_note"] = "not caught up yet at detection: the official rate is %s%% from its value 7 days earlier" % (
            pct(off[base_day], off[d]) if off.get(base_day) and off.get(d) else "unknown")
    mb, ms, src = ok_size
    rec["offers"] = {"source": src, "buy_ads_median_7d": mb, "sell_ads_median_7d": ms,
                     "note": "p2p_sides.csv counts stop at 10 per side; p2p_depth.csv holds the board's own total where stored; "
                             "data/p2p_ads.csv holds every ad read from 22 Oct"}
    rec["timeline"] = timeline(data, ccy, day_add(d, -14), d)
    rec["after"] = []
    rec["checks"] = {
        "er-api": {"file": "data/fx_rates.csv", "readings_on_detection_day": data["n_off"].get((ccy, d), 0),
                   "days_with_a_reading_in_window": sum(1 for n in range(OFFICIAL_DAYS + 1) if off.get(day_add(d, -n)))},
        "fx_live": {"file": "data/fx_live.csv", "days_with_a_reading_in_window": sum(1 for n in range(OFFICIAL_DAYS + 1) if data["live"].get(ccy, {}).get(day_add(d, -n)))},
        "binance_p2p": {"file": "data/p2p_basis.csv", "days_with_a_price_in_window": sum(1 for n in range(STREET_DAYS + 1) if sb.get((ccy, day_add(d, -n))))},
        "okx_p2p": {"file": "data/p2p_okx.csv", "days_with_a_price_in_window": sum(1 for n in range(STREET_DAYS + 1) if data["street"]["okx_p2p"].get((ccy, day_add(d, -n))))},
        "official_rate_rules_flagged_that_day": flagged}
    rec["trace"] = [
        {"number": "official.baseline", "file": "data/fx_rates.csv", "ccy": ccy, "day": day_add(d, -OFFICIAL_DAYS), "rule": "last reading of the UTC day"},
        {"number": "official.at_detection", "file": "data/fx_rates.csv", "ccy": ccy, "day": d, "rule": "last reading of the UTC day"},
        {"number": "street.before", "file": "data/p2p_basis.csv", "ccy": ccy, "day": day_add(d, -STREET_DAYS),
         "rule": "median of the day's binance_p2p buy_median, source_ok true, at least %d readings" % MIN_READINGS},
        {"number": "street.at_detection", "file": "data/p2p_basis.csv", "ccy": ccy, "day": d,
         "rule": "median of the day's binance_p2p buy_median, source_ok true, at least %d readings" % MIN_READINGS}]
    return rec


def timeline(data, ccy, a, b):
    """Daily points from a to b: the official rate (last reading of the day) and the street price (median of the day), None where
    a day has none. Each is one of the stored numbers the trace rules describe."""
    out, d = [], a
    off, st = data["off"].get(ccy, {}), data["street"]["binance_p2p"]
    while d <= b:
        if off.get(d) is not None or st.get((ccy, d)) is not None:
            out.append({"day": d, "official": off.get(d), "street": st.get((ccy, d))})
        d = day_add(d, 1)
    return out


def row(D, rec_id, ccy, kind, status, conf, det, baseline, latest, ch, note):
    return {"as_of_date": D, "event_id": rec_id, "ccy": ccy, "kind": kind, "status": status, "confirmation": conf, "detected_on": det,
            "baseline": "" if baseline is None else baseline, "latest": "" if latest is None else latest,
            "change_pct": "" if ch is None else ch, "note": note}


def step(D, data, events, flags_cache=None):
    """One UTC day D judged with data up to D. `events` are the rows already written (a list of dicts). Returns (new rows, new or
    extended records {id: record})."""
    rows, recs = [], {}
    have = {(e["event_id"], e["status"], e["as_of_date"]) for e in events}
    opened = {}
    for e in events:
        if e["status"] in ("candidate",):
            opened[e["event_id"]] = e
    flags = flags_as_of(D, data["off"], data["live"])
    # two quiet periods, kept apart: a candidate or a data warning keeps the same episode from being raised again for 14 days, but a
    # not_enough_evidence row is only a note that the history was short, so it silences more notes of its own kind and nothing else: the
    # first real break or slide after it must still be raised
    quiet_since, quiet_nee = {}, {}
    for e in events:
        k = (e["ccy"], e["kind"])
        if e["status"] in ("candidate", "data_warning"):
            quiet_since[k] = max(quiet_since.get(k, ""), e["detected_on"])
        elif e["status"] == "not_enough_evidence":
            quiet_nee[k] = max(quiet_nee.get(k, ""), e["detected_on"])
    ccys = sorted(set(data["off"]) | {c for (c, _) in data["street"]["binance_p2p"]})
    for ccy in ccys:
        if ccy == "USD":
            continue
        off = cut(data["off"].get(ccy, {}), D)
        for kind in ("official_break", "street_slide"):
            if kind == "official_break":
                ch = official_step(off, D)
            else:
                ch = street_slide(data["street_c"]["binance_p2p"].get(ccy, {}), D)
            if ch is None:
                continue
            last = quiet_since.get((ccy, kind))
            if last and (dt.date.fromisoformat(D) - dt.date.fromisoformat(last)).days < REARM_DAYS:
                continue                                                                    # the same episode, already on record
            eid = event_id(ccy, kind, D)
            history = len(off)
            t = thick(data["size"], ccy, D)
            warn = None
            if ccy in flags:
                warn = "the official rate is flagged (%s)" % ", ".join(sorted(flags[ccy]))
            elif kind == "official_break" and loop_repeat(off, D):
                warn = "the official rate is back within 2%% of its value %d days earlier, a loop" % loop_repeat(off, D)
            need = MIN_OFFICIAL_HISTORY if kind == "official_break" else MIN_STREET_HISTORY
            if history < need and not warn:
                if kind == "street_slide" and (t is None or not t[0]):
                    continue                                                                # a thin market is not an event, and not a row
                n = quiet_nee.get((ccy, kind))
                if n and (dt.date.fromisoformat(D) - dt.date.fromisoformat(n)).days < REARM_DAYS:
                    continue                                                                # the same note, already on record
                rows.append(row(D, eid, ccy, kind, "not_enough_evidence", "not enough evidence", D, None, None, ch,
                                "%d days of official history, %d are needed" % (history, need)))
                continue
            if warn:
                rows.append(row(D, eid, ccy, kind, "data_warning", "", D, None, None, ch, "would have been %s (%s%%); not an event: %s" % (kind, ch, warn)))
                continue
            if kind == "street_slide":
                if t is None or not t[0]:
                    continue                                                                # a thin market is not an event, and not a row
            conf, srcs = confirmation(kind, data, ccy, D, ch)
            rec = build_record(data, ccy, kind, D, ch, conf, srcs, t[1:] if t else (None, None, "none stored"), flags.get(ccy, []))
            base = rec["official"]["baseline"] if kind == "official_break" else rec["street"]["before"]
            latest = rec["official"]["at_detection"] if kind == "official_break" else rec["street"]["at_detection"]
            rows.append(row(D, eid, ccy, kind, "candidate", conf, D, base, latest, ch,
                            "%s moved %s%% in %d days" % ("the official rate" if kind == "official_break" else "the street price", ch,
                                                           OFFICIAL_DAYS if kind == "official_break" else STREET_DAYS)))
            recs[eid] = rec
    # weekly updates for open events, then the close
    for eid, e in sorted(opened.items()):
        age = (dt.date.fromisoformat(D) - dt.date.fromisoformat(e["detected_on"])).days
        if age <= 0 or age % UPDATE_EVERY or age > CLOSE_AFTER:
            continue
        ccy, kind = e["ccy"], e["kind"]
        s = data["street"]["binance_p2p"].get((ccy, D))
        o = data["off"].get(ccy, {}).get(D)
        o0 = float(e["baseline"]) if kind == "official_break" else data["off"].get(ccy, {}).get(day_add(e["detected_on"], -STREET_DAYS))
        s0 = data["street"]["binance_p2p"].get((ccy, day_add(e["detected_on"], -STREET_DAYS)))
        after = {"day": D, "weeks_after": age // UPDATE_EVERY, "official": o, "street": s,
                 "timeline": timeline(data, ccy, day_add(D, -UPDATE_EVERY + 1), D),
                 "official_change_pct_from_baseline": pct(o0, o) if o0 and o else None,
                 "street_change_pct_from_before": pct(s0, s) if s0 and s else None}
        status = "closed" if age == CLOSE_AFTER else "update"
        rows.append(row(D, eid, ccy, kind, status, e["confirmation"], e["detected_on"], e["baseline"], o if kind == "official_break" else s,
                        after["official_change_pct_from_baseline"] if kind == "official_break" else after["street_change_pct_from_before"],
                        "week %d after, street %s, official %s" % (age // UPDATE_EVERY, s, o)))
        recs[eid] = {"_after": after}
    return rows, recs


# ------------------------------------------------------------------ files

def read_events():
    return read("events.csv")


def first_day(data):
    days = sorted({d for v in data["off"].values() for d in v})
    return days[0] if days else None


def write_rows(rows):
    new = not os.path.exists(EVENTS)
    with open(EVENTS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def add_after(rec, after):
    """Append one weekly snapshot to a record held in memory or just read from its file. Nothing earlier in it changes."""
    if any(x["day"] == after["day"] for x in rec["after"]):
        return
    rec["after"].append(after)
    if after["weeks_after"] * UPDATE_EVERY == CLOSE_AFTER:
        rec["closed_on"] = after["day"]


def write_records(recs):
    """recs: a full record (a new event, with every update that came in the same run already added), or {"_afters": [...]} for updates
    to a record already on file, however many weeks a catch-up run had to cover."""
    os.makedirs(RECORDS, exist_ok=True)
    for eid, rec in recs.items():
        p = os.path.join(RECORDS, eid + ".json")
        if "_afters" in rec:
            cur = json.load(open(p))
            for a in rec["_afters"]:
                add_after(cur, a)
            rec = cur
        elif os.path.exists(p):
            continue                                                                        # a record is written once
        with open(p, "w") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
            f.write("\n")


def run_days(data, events, start, end):
    """Judge every day from start to end (inclusive), feeding each day's rows back in. -> (all new rows, all records)."""
    out, recs = [], {}
    d = start
    while d <= end:
        rows, r = step(d, data, events + out)
        out.extend(rows)
        for k, v in r.items():
            if "_after" not in v:
                recs[k] = v
            elif k in recs and "after" in recs[k]:
                add_after(recs[k], v["_after"])                                             # an event opened earlier in this same run
            else:
                recs.setdefault(k, {"_afters": []})["_afters"].append(v["_after"])           # a record on file: every week, not only the first
        d = day_add(d, 1)
    return out, recs


def main(argv):
    if "--self-test" in argv:
        return self_test()
    data = load()
    yesterday = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    last_fx = max((d for v in data["off"].values() for d in v), default=None)
    end = min(yesterday, last_fx) if last_fx else yesterday
    if "--replay" in argv:
        rows, recs = run_days(data, [], first_day(data), end)
        print_replay(rows)
        return 0
    events = read_events()
    start = day_add(max(e["as_of_date"] for e in events), 1) if events else first_day(data)
    if not start or start > end:
        print("detect_events: nothing new to judge (through %s)" % (start and day_add(start, -1)))
        return 0
    rows, recs = run_days(data, events, start, end)
    write_records(recs)                                                                      # records before rows: persistence before display
    if rows:
        write_rows(rows)
    print("detect_events: judged %s to %s, %d rows" % (start, end, len(rows)))
    print_replay(rows)
    return 0


def print_replay(rows):
    by = {}
    for r in rows:
        by.setdefault(r["status"], []).append(r)
    for st in ("candidate", "not_enough_evidence", "data_warning", "update", "closed"):
        for r in by.get(st, []):
            print("  %s  %-19s %-14s %-4s %-12s %s  %s" % (r["as_of_date"], r["status"], r["kind"], r["ccy"], r["confirmation"] or "-", r["change_pct"], r["note"][:110]))


def self_test():
    # a synthetic world, with a known answer
    base = "2026-09-01"
    days = [day_add(base, i) for i in range(60)]
    off = {"AAA": {d: 100.0 for d in days}, "LUP": {}, "FLT": {d: 50.0 for d in days}}
    for i, d in enumerate(days):
        off["LUP"][d] = [300.0, 280.0, 280.0, 270.0, 250.0, 240.0, 230.0][i % 7]      # a weekly loop (repeats from the second week)
    for i, d in enumerate(days):
        if i >= 40:
            off["AAA"][d] = 130.0                                                         # a 30% official step on day 40
    street = {}
    for i, d in enumerate(days):
        street[("AAA", d)] = 100.0 if i < 36 else 100.0 + (i - 35) * 6                    # the street slides from day 36, ahead of the official step
        street[("THN", d)] = 10.0 if i < 30 else 15.0                                     # a 50% move in a thin market
    size = {(c, d): (40.0, 40.0, "p2p_depth.csv") for c in ("AAA",) for d in days}
    size.update({("THN", d): (3.0, 4.0, "p2p_depth.csv") for d in days})
    sc = {}
    for (c, d), v in street.items():
        sc.setdefault(c, {})[d] = v
    data = {"off": off, "n_off": {}, "live": {}, "street": {"binance_p2p": street, "okx_p2p": {}}, "street_c": {"binance_p2p": sc, "okx_p2p": {}}, "size": size}
    rows, recs = run_days(data, [], days[0], days[-1])
    ev = [(r["ccy"], r["kind"], r["status"], r["detected_on"]) for r in rows if r["status"] in ("candidate", "data_warning", "not_enough_evidence")]
    again, _ = run_days(data, [], days[0], days[-1])
    assert rows == again, "the same input must give the same rows"
    assert ("AAA", "official_break", "candidate", days[40]) in ev, [(r["ccy"], r["kind"], r["status"], r["detected_on"], r["note"]) for r in rows]
    assert any(e[0] == "AAA" and e[1] == "street_slide" and e[2] == "candidate" for e in ev), ev
    assert not [e for e in ev if e[0] == "THN"], "a thin market is not an event: %s" % ev
    assert not [e for e in ev if e[0] == "LUP" and e[2] == "candidate"], "a looping official rate is not an event: %s" % ev
    assert any(e[0] == "LUP" and e[2] in ("data_warning", "not_enough_evidence") for e in ev), ev
    rec = recs[event_id("AAA", "official_break", days[40])]
    assert rec["official"]["baseline"] == 100.0 and rec["official"]["at_detection"] == 130.0 and rec["confirmation"] == "one source", rec
    assert rec["official_lag_days"] is not None and rec["official_lag_days"] > 0, "the street led the official step: %s" % rec["official_lag_note"]
    assert any(r["status"] == "update" and r["event_id"] == rec["id"] for r in rows) or days[40] > days[-8], "weekly updates"
    # catching up across several weekly updates keeps every one of them in the record file (a run that was off for 8 or more days)
    import tempfile
    global RECORDS
    old_records = RECORDS
    with tempfile.TemporaryDirectory() as tmp:
        RECORDS = tmp
        try:
            ev_day = days[40]
            part1, r1 = run_days(data, [], days[0], ev_day)
            write_records(r1)
            eid = event_id("AAA", "official_break", ev_day)
            assert json.load(open(os.path.join(tmp, eid + ".json")))["after"] == [], "a new record starts with no after"
            part2, r2 = run_days(data, part1, day_add(ev_day, 1), day_add(ev_day, 21))       # three weekly update days in one catch-up
            assert set(r2[eid]["_afters"][i]["weeks_after"] for i in range(3)) == {1, 2, 3}, r2[eid]
            write_records(r2)
            rec_on_file = json.load(open(os.path.join(tmp, eid + ".json")))
            assert [a["weeks_after"] for a in rec_on_file["after"]] == [1, 2, 3], "every weekly update reaches the record: %s" % rec_on_file["after"]
            assert rec_on_file["timeline"] == recs[eid]["timeline"], "nothing earlier in the record changes"
            write_records(r2)                                                                  # the same run again adds nothing
            assert [a["weeks_after"] for a in json.load(open(os.path.join(tmp, eid + ".json")))["after"]] == [1, 2, 3]
            # a record opened and updated inside one run holds its updates too, and closes at 8 weeks
            _, r3 = run_days(data, [], days[0], day_add(ev_day, 56) if day_add(ev_day, 56) <= days[-1] else days[-1])
            assert [a["weeks_after"] for a in r3[eid]["after"]] == list(range(1, len(r3[eid]["after"]) + 1)) and r3[eid]["after"], r3[eid]["after"]
        finally:
            RECORDS = old_records
    # a not_enough_evidence note does not silence a real event in the next 14 days, and does not repeat itself for 14 days
    short = [day_add(base, i) for i in range(40)]
    offs = {"NEW": {d: (100.0 if i < 4 else 110.0 if i < 16 else 130.0) for i, d in enumerate(short)}}
    d2 = {"off": offs, "n_off": {}, "live": {}, "street": {"binance_p2p": {}, "okx_p2p": {}}, "street_c": {"binance_p2p": {}, "okx_p2p": {}}, "size": {}}
    r4, _ = run_days(d2, [], short[0], short[-1])
    nee = [r for r in r4 if r["status"] == "not_enough_evidence"]
    cand = [r for r in r4 if r["status"] == "candidate" and r["ccy"] == "NEW"]
    assert [r["detected_on"] for r in nee] == [short[4]], "one note, not one a day: %s" % [r["detected_on"] for r in nee]
    assert [r["detected_on"] for r in cand] == [short[16]], "the real break 12 days after the note must be raised: %s" % [r["detected_on"] for r in cand]
    print("detect_events self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
