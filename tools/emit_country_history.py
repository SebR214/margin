#!/usr/bin/env python3
"""SEB-208: the backfilled history layer, reshaped for a country's chart.

data/history/ (SEB-207) carries venue-reported USDT candles and official daily
rates, each row labelled "reported, not observed". This script is the only
other file allowed to read it (tools/check_history_isolation.py enforces
that, as a listed reader rather than a writer) and it only ever reads -- it
writes a brand new, separate sidecar, data/country_history_segment/<CCY>.json,
that country.html fetches on top of the live index. Nothing here touches
data/countries/, data/index_latest.json or any file the index, a published
price or the unbroken-hours count depends on.

It also writes data/country_history_segment/manifest.json, {"ccys": [...]} --
the list of currencies that got a file this run. country.html reads that
first so it only ever fetches a per-currency file that is known to exist,
rather than firing a 404 for every currency without one.

For a currency with both a venue candle series and an official rate series in
data/history/, index_pct is the same formula emit_countries.py already uses
for the live series -- (price to buy one USDT / official rate - 1) * 100 --
computed once per day the two series overlap, for dates strictly BEFORE the
country's own history_start (data/countries/<CCY>.json), so the sidecar never
overlaps the dates the live chart already shows. A currency with no backfilled
venue (Argentina: no USDT/ARS venue in data/history/) or no official rate
(Taiwan: no ECB series for TWD) gets no file, which is how country.html knows
to say nothing rather than guess.

When one currency has more than one venue (KRW: Bithumb, Coinone, Upbit), the
venue with the earliest first-candle date wins, so the segment reaches back
as far as a real reported price exists.

Largest moves are the biggest day-over-day index_pct changes, found by
sorting -- not chosen by a person or a model.

Stdlib only, no wall clock. Idempotent: re-running with unchanged inputs
writes byte-identical files.

Usage: python3 tools/emit_country_history.py
"""

import csv
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
HIST = os.path.join(DATA, "history")
MANIFEST = os.path.join(HIST, "manifest.json")
FX = os.path.join(HIST, "official_fx_daily.csv")
COUNTRIES_DIR = os.path.join(DATA, "countries")
OUT_DIR = os.path.join(DATA, "country_history_segment")

LABEL = "reported, not observed"
MIN_POINTS = 2
N_LARGEST_MOVES = 3


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def candle_series(path):
    """{date: close}, plus the venue and source every row in this file shares."""
    out, venue, source = {}, None, None
    for r in rows(path):
        date = (r.get("ts_utc") or "")[:10]
        try:
            close = float(r["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if not date or not close:
            continue
        out[date] = close
        venue, source = r.get("venue"), r.get("source")
    return out, venue, source


def fx_series(ccy):
    """{date: per_usd} for one currency, plus the source every row shares."""
    out, source = {}, None
    for r in rows(FX):
        if r.get("ccy") != ccy:
            continue
        date = r.get("date")
        try:
            per_usd = float(r["per_usd"])
        except (KeyError, TypeError, ValueError):
            continue
        if not date or not per_usd:
            continue
        out[date] = per_usd
        source = r.get("source")
    return out, source


def history_start(ccy):
    """The date the LIVE chart's own series already starts from, or None."""
    path = os.path.join(COUNTRIES_DIR, ccy + ".json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return (json.load(f) or {}).get("history_start")


def pick_candle_file(manifest, ccy):
    """The daily-candle venue for this currency with the deepest history."""
    best = None
    for entry in manifest.get("files", {}).values():
        if entry.get("ccy") != ccy or not entry.get("file", "").endswith("_1d.csv"):
            continue
        if best is None or entry["first"] < best["first"]:
            best = entry
    return best


def largest_moves(points, n=N_LARGEST_MOVES):
    moves = [{"date": points[i]["date"], "index_pct": points[i]["index_pct"],
              "delta_pct": round(points[i]["index_pct"] - points[i - 1]["index_pct"], 4)}
             for i in range(1, len(points))]
    moves.sort(key=lambda m: abs(m["delta_pct"]), reverse=True)
    return moves[:n]


def build_one(manifest, ccy):
    candle_entry = pick_candle_file(manifest, ccy)
    if not candle_entry:
        return None
    fx, fx_source = fx_series(ccy)
    if not fx:
        return None
    candles, venue, venue_source = candle_series(os.path.join(HERE, candle_entry["file"]))
    if not candles:
        return None
    cutoff = history_start(ccy)
    dates = sorted(d for d in candles if d in fx and (cutoff is None or d < cutoff))
    if len(dates) < MIN_POINTS:
        return None
    points = [{"date": d, "index_pct": round((candles[d] / fx[d] - 1) * 100, 4)} for d in dates]
    return {
        "ccy": ccy,
        "label": LABEL,
        "venue": venue,
        "venue_source": venue_source,
        "fx_source": fx_source,
        "first": points[0]["date"],
        "last": points[-1]["date"],
        "n": len(points),
        "points": points,
        "largest_moves": largest_moves(points),
    }


def build():
    with open(MANIFEST) as f:
        manifest = json.load(f)
    ccys = sorted({entry["ccy"] for entry in manifest["files"].values() if "ccy" in entry})
    os.makedirs(OUT_DIR, exist_ok=True)
    written = set()
    for ccy in ccys:
        doc = build_one(manifest, ccy)
        if doc is None:
            continue
        with open(os.path.join(OUT_DIR, ccy + ".json"), "w") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
        written.add(ccy)
    # A currency that no longer qualifies (cutoff moved, source dropped out)
    # loses its stale file rather than leaving an outdated segment on its page.
    for name in os.listdir(OUT_DIR):
        if name.endswith(".json") and name != "manifest.json" and name[:-5] not in written:
            os.remove(os.path.join(OUT_DIR, name))
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"ccys": sorted(written)}, f, indent=1)
        f.write("\n")
    return sorted(written)


if __name__ == "__main__":
    done = build()
    print(f"wrote {len(done)} country-history segments: {', '.join(done)}")
