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
as far as a real reported price exists. Two guards keep a broken series off
the page without altering a row: only a venue's newest stretch with no hole
longer than 31 days is used (India: WazirX was halted for 15 months, so its
segment starts after the halt), and a venue with any print further than 50%
from the official rate in that stretch (CoinDCX's illiquid 2019-2020 prints,
one stray MAX print) is passed over for the next venue.

Taiwan's official rate is the Taiwan central bank's own series (CBC, via the
same Frankfurter host), since the ECB publishes none.

Largest moves are the biggest day-over-day index_pct changes, found by
sorting -- not chosen by a person or a model.

Stdlib only, no wall clock. Idempotent: re-running with unchanged inputs
writes byte-identical files.

Widened 24 Oct 2026 (SEB-301, Seb in chat): the SEB-311 wide pull is read too.
Candles: the stablecoin pairs (USDT priced in the local currency) in Binance spot,
Bitso, Buda and CoinGecko's daily files, besides the SEB-207 venues. Official rate
per day: the central-bank series (BIS) first, then the ECB/CBC file, then
fawazahmed0, then Frankfurter v2. The 50% guard became a spike guard, because a
real gap can be far above 50% (Argentina 2023): a day further than 25 points
from the median of the 7 days around it is left out, and a venue where more than
2% of days are spikes is passed over. One venue per currency, deepest first, as
before.

Usage: python3 tools/emit_country_history.py
"""

import csv
import datetime
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
MAX_GAP_DAYS = 31
SPIKE_PTS = 25.0          # a day this far from the median of the 7 days around it is a spike
MAX_SPIKE_SHARE = 0.02    # a venue with more spikes than this is passed over
# the SEB-311 wide pull: (file, pair test) -- only USDT priced in the local currency
WIDE_CANDLES = [
    ("data/history/candles_binance_spot_1d.csv", lambda ccy, pair: pair == "USDT" + ccy),
    ("data/history/candles_bitso_wide_1d.csv", lambda ccy, pair: pair == "usdt_" + ccy.lower()),
    ("data/history/candles_buda_1d.csv", lambda ccy, pair: pair == "USDT-" + ccy),
    ("data/history/candles_coingecko_1d.csv", lambda ccy, pair: pair == "USDT-" + ccy),
]
# official rate per day, first file that has the day wins
FX_FILES = ["official_fx_bis_daily.csv", "official_fx_daily.csv", "official_fx_fawaz_daily.csv",
            "official_fx_frankfurter_v2_daily.csv"]
N_LARGEST_MOVES = 3


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


_ROWS = {}


def cached_rows(path):
    if path not in _ROWS:
        _ROWS[path] = rows(path)
    return _ROWS[path]


def candle_series(path, ccy=None, pair_ok=None):
    """{date: close}, plus the venue and source every row in this file shares.
    For a multi-currency file, ccy and pair_ok pick one stablecoin pair."""
    out, venue, source = {}, None, None
    for r in cached_rows(path):
        if pair_ok is not None and (r.get("ccy") != ccy or not pair_ok(ccy, r.get("pair") or "")):
            continue
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
    """{date: per_usd} for one currency, the first file in FX_FILES that has the
    day, plus the source of each file used, in that order."""
    out, sources = {}, []
    for name in FX_FILES:
        used = None
        for r in cached_rows(os.path.join(HIST, name)):
            if r.get("ccy") != ccy:
                continue
            date = r.get("date")
            try:
                per_usd = float(r["per_usd"])
            except (KeyError, TypeError, ValueError):
                continue
            if not date or not per_usd or date in out:
                continue
            out[date] = per_usd
            used = r.get("source")
        if used and used not in sources:
            sources.append(used)
    return out, "; ".join(sources) or None


def drop_spikes(pts):
    """Leave out days far from the median of the 7 days around them. Returns the
    kept points and how many were left out."""
    keep, dropped = [], 0
    vals = [p["index_pct"] for p in pts]
    for i, p in enumerate(pts):
        win = sorted(vals[max(0, i - 3):i] + vals[i + 1:i + 4])
        if len(win) >= 4:
            med = win[len(win) // 2] if len(win) % 2 else (win[len(win) // 2 - 1] + win[len(win) // 2]) / 2
            if abs(p["index_pct"] - med) > SPIKE_PTS:
                dropped += 1
                continue
        keep.append(p)
    return keep, dropped


def history_start(ccy):
    """The date the LIVE chart's own series already starts from, or None."""
    path = os.path.join(COUNTRIES_DIR, ccy + ".json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return (json.load(f) or {}).get("history_start")


def candle_entries(manifest, ccy):
    """Daily-candle venues for this currency, deepest history first."""
    found = [e for e in manifest.get("files", {}).values()
             if e.get("ccy") == ccy and e.get("file", "").endswith("_1d.csv")]
    return sorted(found, key=lambda e: e["first"])


def latest_run(dates):
    """The newest stretch of dates with no hole longer than MAX_GAP_DAYS -- the
    stretch that abuts the live chart. Dates before a longer hole are dropped,
    never bridged."""
    ds = [datetime.date.fromisoformat(d) for d in dates]
    start = 0
    for i in range(1, len(ds)):
        if (ds[i] - ds[i - 1]).days > MAX_GAP_DAYS:
            start = i
    return dates[start:]


def largest_moves(points, n=N_LARGEST_MOVES):
    moves = [{"date": points[i]["date"], "index_pct": points[i]["index_pct"],
              "delta_pct": round(points[i]["index_pct"] - points[i - 1]["index_pct"], 4)}
             for i in range(1, len(points))]
    moves.sort(key=lambda m: abs(m["delta_pct"]), reverse=True)
    return moves[:n]


def build_one(manifest, ccy):
    fx, fx_source = fx_series(ccy)
    if not fx:
        return None
    cutoff = history_start(ccy)
    # One candidate per venue: its newest unbroken stretch (an exchange halt is
    # a hole, not something to draw a line across). A venue with any print
    # further than MAX_ABS_PCT from the official rate is a broken series in this
    # window (a stray order, an illiquid early market) and is passed over, not
    # trimmed. Among what is left the deepest stretch wins.
    best = None
    sources = [(os.path.join(HERE, e["file"]), None) for e in candle_entries(manifest, ccy)]
    sources += [(os.path.join(HERE, path), test) for path, test in WIDE_CANDLES]
    for path, test in sources:
        candles, venue, venue_source = candle_series(path, ccy, test) if test else candle_series(path)
        if not candles:
            continue
        dates = latest_run(sorted(d for d in candles
                                  if d in fx and (cutoff is None or d < cutoff)))
        pts = [{"date": d, "index_pct": round((candles[d] / fx[d] - 1) * 100, 4)}
               for d in dates]
        if len(pts) < MIN_POINTS:
            continue
        pts, dropped = drop_spikes(pts)
        if len(pts) < MIN_POINTS or dropped > MAX_SPIKE_SHARE * (len(pts) + dropped):
            continue
        if best is None or pts[0]["date"] < best[0][0]["date"]:
            best = (pts, venue, venue_source)
    if best is None:
        return None
    points, venue, venue_source = best
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
    ccys = {entry["ccy"] for entry in manifest["files"].values() if "ccy" in entry}
    ccys |= {name[:-5] for name in os.listdir(COUNTRIES_DIR) if name.endswith(".json") and len(name) == 8}
    ccys = sorted(ccys)
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
