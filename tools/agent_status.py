#!/usr/bin/env python3
"""What the robot is doing, and whether anything is quietly broken.

Writes data/agent_status.json, which /status.html renders and the product agent
reads before it files anything. Every figure here is read off a file in data/;
nothing is estimated, and a check that could not run is reported as "unknown"
rather than as a pass.

Health is decided on the DAY BEFORE the newest one in the data. Today is always
partial, and calling a partial day a delivery failure is how you get an agent
filing a bug every morning.

Stdlib only. Usage: python3 tools/agent_status.py
"""

import csv
import datetime as dt
import glob
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "agent_status.json")
LOGDIR = "/var/log/margin"

# A source silent this long is broken, not late.
STALE_HOURS = 3
# A published country moving this far in a day is either a story or a bug.
BIG_MOVE_PT = 5.0
# ...unless its official rate moved too, in which case it is just the currency.
FX_EXPLAINS_PCT = 2.0


def exceptions():
    """Sources known to be correctly recording an absence. See the file itself."""
    p = os.path.join(HERE, "tools", "source_exceptions.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}


def rows(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def stamp(r):
    return (r.get("ts_utc") or r.get("ts") or "").strip()


def num(v):
    try:
        x = float(str(v).strip())
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def delivery():
    """Hours of the day that produced at least one sample."""
    by_day = {}
    for r in rows("samples.csv"):
        s = stamp(r)
        if len(s) >= 13:
            by_day.setdefault(s[:10], set()).add(s[11:13])
    days = sorted(by_day)
    return ([{"date": d, "hours": len(by_day[d])} for d in days[-8:]],
            days[-1] if days else None)


def sources(newest):
    """Every collector that records source_ok: is it answering, and since when?

    Keyed by the column that names the thing being collected, so a single dead
    venue is visible instead of being averaged into a healthy file.
    """
    files = {
        "basis.csv": "venue", "p2p_basis.csv": "ccy",
        "provider_quotes.csv": "provider", "providers.csv": "provider",
        "providers_usdmxn.csv": "provider", "providers_audphp.csv": "provider",
        "providers_nzdphp.csv": "provider", "samples.csv": "corridor",
        "stable_spread.csv": "venue",
    }
    known = exceptions()
    out = []
    for fname, key in files.items():
        data = rows(fname)
        if not data:
            continue
        last_ok, last_seen = {}, {}
        for r in data:
            name = (r.get(key) or "?").strip()
            s = stamp(r)
            if not s:
                continue
            last_seen[name] = max(last_seen.get(name, ""), s)
            if (r.get("source_ok") or "").strip().lower() == "true":
                last_ok[name] = max(last_ok.get(name, ""), s)
        for name in sorted(last_seen):
            ok = last_ok.get(name)
            hours = None
            if ok and newest:
                try:
                    hours = round(
                        (dt.datetime.fromisoformat(newest)
                         - dt.datetime.fromisoformat(ok)).total_seconds() / 3600, 1)
                except ValueError:
                    hours = None
            silent = known.get(fname, {}).get(name)
            out.append({
                "file": fname, "name": name,
                "last_ok_utc": ok, "last_seen_utc": last_seen[name],
                "hours_since_ok": hours,
                "expected_silent": silent,
                "broken": (ok is None or (hours is not None and hours > STALE_HOURS))
                          and not silent,
            })
    return out


def fx_daily():
    """Daily median official and parallel rate per currency."""
    off, par = {}, {}
    for r in rows("fx_rates.csv"):
        s, c = stamp(r), (r.get("ccy") or "").strip()
        if len(s) < 10 or not c:
            continue
        v = num(r.get("fx_mid_per_usd"))
        if v:
            off.setdefault((c, s[:10]), []).append(v)
        p = num(r.get("parallel_rate_per_usd"))
        if p:
            par.setdefault((c, s[:10]), []).append(p)
    return ({k: st.median(v) for k, v in off.items()},
            {k: st.median(v) for k, v in par.items()})


def moves():
    """Published countries whose price jumped without their currency moving.

    Both numbers are always reported, never just the flag: a 5-point move is
    ordinary when the currency moved and is a story when it did not, and the
    only way to tell them apart is to put the two side by side.
    """
    official, parallel = fx_daily()
    out = []
    for path in sorted(glob.glob(os.path.join(DATA, "countries", "*.json"))):
        try:
            with open(path) as f:
                c = json.load(f)
        except (OSError, ValueError):
            continue
        hist = [h for h in (c.get("history") or [])
                if h.get("date") and num(h.get("index_pct")) is not None]
        if len(hist) < 2:
            continue
        hist.sort(key=lambda h: h["date"])
        a, b = hist[-2], hist[-1]
        move = num(b["index_pct"]) - num(a["index_pct"])
        ccy = c.get("ccy")
        fx_move = par_move = None
        f0, f1 = official.get((ccy, a["date"])), official.get((ccy, b["date"]))
        if f0 and f1:
            fx_move = round((f1 - f0) / f0 * 100, 3)
        p0, p1 = parallel.get((ccy, a["date"])), parallel.get((ccy, b["date"]))
        if p0 and p1:
            par_move = round((p1 - p0) / p0 * 100, 3)
        explained = any(m is not None and abs(m) >= FX_EXPLAINS_PCT
                        for m in (fx_move, par_move))
        out.append({
            "ccy": ccy, "country": c.get("country"),
            "from_date": a["date"], "to_date": b["date"],
            "index_move_pt": round(move, 3),
            "official_move_pct": fx_move, "parallel_move_pct": par_move,
            "unexplained": abs(move) > BIG_MOVE_PT and not explained,
        })
    out.sort(key=lambda m: -abs(m["index_move_pt"]))
    return out


def withheld():
    p = os.path.join(DATA, "index_latest.json")
    if not os.path.exists(p):
        return {"today": None, "previous": None, "change": None, "as_of": None}
    with open(p) as f:
        ix = json.load(f)
    return {"today": len(ix.get("withheld") or []),
            "published": len(ix.get("countries") or []),
            "as_of": ix.get("as_of_utc"),
            "reasons": sorted({w.get("reason_raw") or w.get("reason") or "?"
                               for w in (ix.get("withheld") or [])})}


def loops():
    """Last run of each agent, from the log the runner writes. Absent is absent."""
    out = {}
    for role in ("builder", "reviewer", "product"):
        p = os.path.join(LOGDIR, role + ".jsonl")
        if not os.path.exists(p):
            out[role] = None
            continue
        last = None
        try:
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            last = json.loads(line)
                        except ValueError:
                            pass
        except OSError:
            last = None
        out[role] = last
    return out


def main():
    days, newest_day = delivery()
    newest = ""
    for r in rows("samples.csv")[-400:]:
        newest = max(newest, stamp(r))
    judged = days[-2] if len(days) >= 2 else None

    src = sources(newest)
    mv = moves()
    payload = {
        "as_of_utc": newest or None,
        "judged_day": judged,
        "delivery": days,
        "delivery_ok": (judged["hours"] >= 23) if judged else None,
        "sources": src,
        "sources_broken": [s for s in src if s["broken"]],
        "sources_expected_silent": [s for s in src if s.get("expected_silent")],
        "withheld": withheld(),
        "moves": mv[:20],
        "moves_unexplained": [m for m in mv if m["unexplained"]],
        "loops": loops(),
        "thresholds": {"delivery_hours": 23, "stale_hours": STALE_HOURS,
                       "big_move_pt": BIG_MOVE_PT,
                       "fx_explains_pct": FX_EXPLAINS_PCT},
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")

    print(f"  as of            {payload['as_of_utc']}")
    if judged:
        print(f"  delivery         {judged['date']}  {judged['hours']}/24"
              f"  {'ok' if payload['delivery_ok'] else 'BELOW 23'}")
    else:
        print("  delivery         unknown -- not enough days to judge")
    print(f"  sources          {len(src)} tracked, "
          f"{len(payload['sources_broken'])} not answering, "
          f"{len(payload['sources_expected_silent'])} silent by design")
    for s in payload["sources_broken"][:8]:
        print(f"                     {s['file']}:{s['name']} "
              f"last ok {s['last_ok_utc'] or 'never'}")
    w = payload["withheld"]
    print(f"  countries        {w['published']} published, {w['today']} withheld")
    print(f"  unexplained move {len(payload['moves_unexplained'])}")
    for m in payload["moves_unexplained"][:5]:
        print(f"                     {m['ccy']} {m['index_move_pt']:+.2f} pt, "
              f"official {m['official_move_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
