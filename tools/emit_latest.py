#!/usr/bin/env python3
"""Machine-readable snapshot of the current state: data/latest.json.

The CSVs are the archive -- append-only, hourly, and increasingly large. This
is the other half: one small static file holding only the *newest* state of
every layer, regenerated each collector run and committed alongside the rows it
summarises. A researcher can ingest the whole instrument with one GET of
https://margin.wiki/data/latest.json instead of parsing five growing CSVs.

Derived, never authoritative -- including its own clock. `as_of_utc` is the
newest source timestamp among the rows that fed the file, NOT the time the
script ran. There is no wall clock anywhere in the output, which makes the
snapshot a pure function of the data: a collector run that changes nothing
regenerates a byte-identical file. That is what keeps the commit step's
"nothing staged" branch reachable, and with it `tools/check_freshness.py`.
It also matches how the rest of the repo works -- outputs derive from data,
never from when a script happened to fire.

Every value here is copied or computed from a CSV row; nothing is invented,
interpolated, or defaulted. That has two consequences worth stating, because
they look like bugs and are not:

  - A missing or empty CSV produces an ABSENT KEY, never a placeholder value.
    Absent means "not collected"; a zero would be a claim about the market.
  - `null` inside a row means the CSV cell was empty or unparseable. Gaps stay
    gaps here exactly as they do in the CSVs.

Bad rows are SKIPPED, never fatal: a half-written row must not cost the whole
snapshot. The only failure that exits non-zero is being unable to write the
file -- the one condition that leaves consumers reading a stale snapshot with
no signal that anything went wrong.

Stdlib only. Usage: python3 tools/emit_latest.py
"""

import csv
import datetime as dt
import statistics
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "latest.json")
CROSSES = os.path.join(DATA, "crosses_latest.json")

BASIS = os.path.join(DATA, "basis.csv")
SAMPLES = os.path.join(DATA, "samples.csv")

# Panel files are per-corridor: providers.csv has no corridor column and a
# frozen schema, so each corridor writes its own file. Listed explicitly rather
# than imported from collector.py -- this tool is stdlib-only and must keep
# working even if the collector cannot be imported (it needs `requests`).
# A file that is not present is simply not reported.
PANELS = [
    ("SGD->PHP", "providers.csv"),
    ("USD->MXN", "providers_usdmxn.csv"),
]


# ------------------------------------------------------------- parsing
def rows(path):
    """Every readable row of a CSV. Unreadable file -> no rows, no exception."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def num(row, key):
    """Float from a cell, or None. An empty or junk cell is a gap, not a zero."""
    try:
        v = row.get(key)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def flag(row, key):
    """CSV writes booleans as 'True'/'False'. Anything else is unknown -> None."""
    v = (row.get(key) or "").strip().lower()
    return True if v == "true" else False if v == "false" else None


def parse_ts(s):
    """ISO string -> aware datetime, or None. Naive stamps are read as UTC."""
    try:
        t = dt.datetime.fromisoformat(s or "")
    except (TypeError, ValueError):
        return None
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t


def ts_of(row, key):
    """Parsed timestamp for ordering, or None if the cell is unusable."""
    return parse_ts(row.get(key))


def newest(rs, key):
    """The single latest timestamp among `rs`, or None if none parse."""
    stamps = [t for t in (ts_of(r, key) for r in rs) if t is not None]
    return max(stamps) if stamps else None


# ------------------------------------------------------------- sections
def basis_section():
    """Latest row per venue in basis.csv."""
    best = {}
    for r in rows(BASIS):
        venue, t = r.get("venue"), ts_of(r, "ts_utc")
        if not venue or t is None:
            continue                      # a row with no venue or no clock is unusable
        if venue not in best or t > best[venue][0]:
            best[venue] = (t, r)
    out = []
    for venue in sorted(best):
        _, r = best[venue]
        out.append({
            "venue": venue,
            "ccy": r.get("ccy") or None,
            "basis_bps": num(r, "basis_bps"),
            "ts_utc": r.get("ts_utc"),
            "source_ok": flag(r, "source_ok"),
        })
    return out


# A CriptoYa "(CCY)" row is a median across exchanges, not a venue. It is still
# published in `basis` (it keys the pre-2026-09 history and the daily backfill)
# but it must never be one of the venues in a cross-venue median -- that would
# put a median next to its own inputs and count it twice. Named by pattern
# rather than imported from collector_basis.py, which needs `requests`: this
# tool is stdlib-only on purpose, the same reason captured_this_hour() is
# duplicated rather than shared.
def is_aggregate(venue):
    return venue.startswith("CriptoYa (") and venue.endswith(")")


def markets_section():
    """Per-currency cross-venue view: median basis, and the spread around it.

    One venue per country was the whole weakness: a single exchange's quote,
    presented as a country's number. This groups every venue that answered in
    the SAME UTC HOUR -- comparing a Seoul print from 14:00 with a Sao Paulo
    print from 09:00 would be a spread of the clock, not of the market -- and
    reports the median across them.

    `basis_median_bps` and `basis_spread_bps` appear ONLY where two or more
    venues answered that hour. With one venue there is no median to take and no
    spread to measure, and emitting the lone venue's number under a name that
    implies agreement would be exactly the overstatement this replaces. In that
    case `venues` still lists the one, `venue_count` is 1, and both derived
    keys are absent -- absent meaning "not measurable", the same contract as
    every other absent key in this file.

    Spread is max minus min basis, in bps: the disagreement between the venues,
    not a bid/ask spread. A wide one is a real signal (thin books, a stale
    quote, a fragmented market) and is shown rather than smoothed away.
    """
    by_ccy = {}
    for r in rows(BASIS):
        venue, ccy, t = r.get("venue"), r.get("ccy"), ts_of(r, "ts_utc")
        if not venue or not ccy or t is None:
            continue
        if not flag(r, "source_ok"):
            continue                      # a failed pull is not a venue answering
        if num(r, "basis_bps") is None:
            continue
        hour = t.replace(minute=0, second=0, microsecond=0)
        # Newest hour wins; an older hour's venues are discarded outright rather
        # than merged in to pad the count.
        cur = by_ccy.get(ccy)
        if cur is None or hour > cur["hour"]:
            by_ccy[ccy] = {"hour": hour, "venues": {}}
            cur = by_ccy[ccy]
        if hour < cur["hour"]:
            continue
        # Within the hour the latest row for a venue wins, so a rescue fire
        # cannot make one venue count twice.
        prev = cur["venues"].get(venue)
        if prev is None or t > prev[0]:
            cur["venues"][venue] = (t, r)

    out = {}
    for ccy in sorted(by_ccy):
        entries = by_ccy[ccy]["venues"]
        listed = [{
            "venue": v,
            "basis_bps": num(r, "basis_bps"),
            "ts_utc": r.get("ts_utc"),
            "aggregate": is_aggregate(v),
        } for v, (_, r) in sorted(entries.items())]
        if not listed:
            continue
        # Aggregates are listed -- for VES and BRL the CriptoYa aggregate is the
        # longest-running number there is, and dropping it from the output
        # would hide it from the site entirely -- but they are not venues, so
        # they are counted by neither venue_count nor the median.
        vals = [e["basis_bps"] for e in listed if not e["aggregate"]]
        entry = {
            "venues": listed,
            "venue_count": len(vals),
            "hour_utc": by_ccy[ccy]["hour"].isoformat(),
        }
        if len(vals) >= 2:
            entry["basis_median_bps"] = round(statistics.median(vals), 2)
            entry["basis_spread_bps"] = round(max(vals) - min(vals), 2)
        out[ccy] = entry
    return out


def crosses_section():
    """Every currency pair, priced two ways: through USDT, and officially.

    Pure arithmetic on rows already collected -- nothing new is fetched. For a
    pair A/B, the crypto route is: sell one unit of A for USDT on an A-quoted
    venue, then buy B with that USDT on a B-quoted venue. So

        implied_rate (B per A) = usdt_mid_B / usdt_mid_A
        official_rate (B per A) = fx_mid_per_usd_B / fx_mid_per_usd_A
        gap_pct = (implied / official - 1) * 100

    This is a MARKET-PRICE comparison, not a cost quote. It carries no exchange
    fee, no spread crossed, no withdrawal fee and no network fee: those live in
    the corridor layer, where they are verified against published schedules.
    A reader who sends money along this route will not get `implied_rate`. What
    the gap shows is how far the two markets' view of a cross has drifted from
    the official one, which is the whole point of measuring basis at all.

    Only pairs where BOTH legs were captured in the SAME UTC hour are emitted.
    A cross built from a Manila print and a five-hour-old Istanbul print would
    be measuring the clock. Currencies whose newest hour differs are simply not
    paired, and the pair is absent rather than stale.

    Per currency the price is the median across the exchanges that reported
    that hour -- the same number the board shows -- falling back to the
    aggregated feed where no individual exchange reported (ARS/VES/BRL history).
    """
    by_ccy = {}
    for r in rows(BASIS):
        ccy, t = r.get("ccy"), ts_of(r, "ts_utc")
        if not ccy or t is None or not flag(r, "source_ok"):
            continue
        mid, fx = num(r, "usdt_mid"), num(r, "fx_mid_per_usd")
        if mid is None or fx is None or mid <= 0 or fx <= 0:
            continue
        hour = t.replace(minute=0, second=0, microsecond=0)
        cur = by_ccy.get(ccy)
        if cur is None or hour > cur["hour"]:
            cur = by_ccy[ccy] = {"hour": hour, "mids": {}, "aggs": {}, "fx": fx,
                                 "ts": r.get("ts_utc")}
        if hour < cur["hour"]:
            continue
        target = cur["aggs"] if is_aggregate(r.get("venue") or "") else cur["mids"]
        target[r.get("venue")] = mid
        cur["fx"] = fx
        cur["ts"] = r.get("ts_utc")

    price = {}
    for ccy, e in by_ccy.items():
        vals = list(e["mids"].values()) or list(e["aggs"].values())
        if not vals:
            continue
        price[ccy] = {"mid": statistics.median(vals), "fx": e["fx"],
                      "hour": e["hour"], "ts": e["ts"],
                      "venues": len(e["mids"]) or len(e["aggs"])}

    out = {}
    codes = sorted(price)
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            pa, pb = price[a], price[b]
            if pa["hour"] != pb["hour"]:
                continue                  # different hours -> no pair, not a stale one
            implied = pb["mid"] / pa["mid"]
            official = pb["fx"] / pa["fx"]
            if official <= 0:
                continue
            out[f"{a}/{b}"] = {
                "base": a, "quote": b,
                "implied_rate": round(implied, 8),
                "official_rate": round(official, 8),
                "gap_pct": round((implied / official - 1) * 100, 4),
                "ts_utc": max(pa["ts"], pb["ts"]),
                "hour_utc": pa["hour"].isoformat(),
                "venues": {a: pa["venues"], b: pb["venues"]},
            }
    return out


def corridors_section():
    """Latest full ladder per corridor in samples.csv.

    Both corridors share samples.csv and interleave, so "latest" is resolved
    per corridor, not by reading the tail of the file.
    """
    by_corridor = {}
    for r in rows(SAMPLES):
        key = r.get("corridor")
        if key and ts_of(r, "ts") is not None:
            by_corridor.setdefault(key, []).append(r)

    out = {}
    for key in sorted(by_corridor):
        rs = by_corridor[key]
        latest = newest(rs, "ts")
        if latest is None:
            continue
        ladder = [r for r in rs if ts_of(r, "ts") == latest]
        sizes = []
        for r in sorted(ladder, key=lambda r: num(r, "notional_src") or 0):
            size = num(r, "notional_src")
            if size is None:
                continue                  # a ladder rung with no size cannot be keyed
            sizes.append({
                "notional_src": size,
                "cost_bps_taker": num(r, "cost_bps_taker"),
                "cost_bps_maker": num(r, "cost_bps_maker"),
                "baseline_provider": r.get("baseline_provider") or None,
                "baseline_cost_bps": num(r, "baseline_cost_bps"),
                "crypto_wins_taker": flag(r, "crypto_wins_taker"),
            })
        if not sizes:
            continue
        r0 = ladder[0]
        out[key] = {
            "ts": r0.get("ts"),
            "src": r0.get("src") or None,
            "dst": r0.get("dst") or None,
            "fees_verified": r0.get("fees_verified") or None,
            "source_ok": flag(r0, "source_ok"),
            "sizes": sizes,
        }
    return out


def panel_section(path):
    """Best and worst provider by cost at each size, from the file's latest ts.

    Cheapest = lowest cost_bps (bps below mid), matching the corridor's own
    convention, so these are directly comparable to cost_bps_taker/maker.
    Rows without a usable cost are skipped: a provider that failed to quote
    must not become the 'worst' rail by default.
    """
    rs = [r for r in rows(path) if flag(r, "source_ok") and num(r, "cost_bps") is not None]
    latest = newest(rs, "ts_utc")
    if latest is None:
        return None
    current = [r for r in rs if ts_of(r, "ts_utc") == latest]

    by_size = {}
    for r in current:
        size = num(r, "notional_src")
        if size is not None:
            by_size.setdefault(size, []).append(r)
    if not by_size:
        return None

    def one(r):
        return {"provider": r.get("provider") or None, "cost_bps": num(r, "cost_bps")}

    sizes = []
    for size in sorted(by_size):
        group = sorted(by_size[size], key=lambda r: num(r, "cost_bps"))
        sizes.append({
            "notional_src": size,
            "providers_quoting": len(group),
            "best": one(group[0]),
            "worst": one(group[-1]),
        })
    return {"ts_utc": current[0].get("ts_utc"), "sizes": sizes}


def providers_section():
    """One entry per corridor panel file that exists and has usable rows."""
    out = {}
    for corridor, name in PANELS:
        section = panel_section(os.path.join(DATA, name))
        if section is not None:
            section["source"] = f"data/{name}"
            out[corridor] = section
    return out


# ---------------------------------------------------------------- main
def as_of(snap):
    """Newest source timestamp among the rows that fed the snapshot.

    Read back off the emitted values, so it is by construction a stamp that
    appears verbatim in a CSV row rather than a number this script invented.
    None when nothing was collected -- then the key is absent like any other.
    """
    stamps = [e.get("ts_utc") for e in snap.get("basis", [])]
    stamps += [v.get("ts") for v in snap.get("corridors", {}).values()]
    stamps += [v.get("ts_utc") for v in snap.get("providers", {}).values()]
    parsed = [(t, s) for s, t in ((s, parse_ts(s)) for s in stamps) if t is not None]
    return max(parsed)[1] if parsed else None


def build():
    """The snapshot. Empty sections are omitted, never emitted as placeholders.

    Deliberately contains NO wall clock: identical inputs must produce an
    identical file, byte for byte.
    """
    snap = {}
    sources = []

    basis = basis_section()
    if basis:
        snap["basis"] = basis
        sources.append("data/basis.csv")

    markets = markets_section()
    if markets:
        snap["markets"] = markets
        sources.append("data/basis.csv")

    corridors = corridors_section()
    if corridors:
        snap["corridors"] = corridors
        sources.append("data/samples.csv")

    providers = providers_section()
    if providers:
        snap["providers"] = providers
        sources.extend(v["source"] for v in providers.values())

    if sources:
        snap["sources"] = sorted(set(sources))

    stamp = as_of(snap)
    if stamp is not None:
        snap["as_of_utc"] = stamp
    return snap


def build_crosses():
    """The crosses file. Its own file, not a key in latest.json: it is a
    different question (a pair of markets against each other) at a different
    shape (45 pairs), and latest.json is meant to stay small enough to read.

    Same contract as latest.json: no wall clock, so identical inputs produce an
    identical file and the collector's "nothing staged" branch stays reachable.
    """
    pairs = crosses_section()
    snap = {}
    if pairs:
        snap["pairs"] = pairs
        snap["source"] = "data/basis.csv"
        stamps = [(parse_ts(v["ts_utc"]), v["ts_utc"]) for v in pairs.values()]
        stamps = [(t, s) for t, s in stamps if t is not None]
        if stamps:
            snap["as_of_utc"] = max(stamps)[1]
    return snap


def main():
    snap = build()
    crosses = build_crosses()
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(snap, f, indent=2, sort_keys=True)
            f.write("\n")
        with open(CROSSES, "w") as f:
            json.dump(crosses, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        # The ONLY fatal case: consumers would otherwise keep reading a stale
        # snapshot with nothing to tell them it stopped being regenerated.
        print(f"  [error] cannot write {OUT}: {e}", file=sys.stderr)
        sys.exit(1)

    present = [k for k in ("basis", "markets", "corridors", "providers") if k in snap]
    missing = [k for k in ("basis", "markets", "corridors", "providers") if k not in snap]
    print(f"  wrote {os.path.relpath(OUT, HERE)} "
          f"({os.path.getsize(OUT):,} bytes)")
    if "as_of_utc" in snap:
        print(f"    as of      : {snap['as_of_utc']} (newest source row)")
    if "basis" in snap:
        print(f"    basis      : {len(snap['basis'])} venues")
    if crosses.get("pairs"):
        gaps = [abs(v["gap_pct"]) for v in crosses["pairs"].values()]
        widest = max(crosses["pairs"].items(), key=lambda kv: abs(kv[1]["gap_pct"]))
        print(f"  wrote {os.path.relpath(CROSSES, HERE)} "
              f"({len(crosses['pairs'])} pairs, widest {widest[0]} "
              f"{widest[1]['gap_pct']:+.2f}%, median gap "
              f"{statistics.median(gaps):.2f}%)")
    else:
        print(f"  no crosses written -- no two currencies share a captured hour")
    if "markets" in snap:
        multi = sum(1 for v in snap["markets"].values() if "basis_median_bps" in v)
        print(f"    markets    : {len(snap['markets'])} currencies, "
              f"{multi} with 2+ venues this hour")
        for ccy, v in sorted(snap["markets"].items()):
            if "basis_median_bps" in v:
                print(f"      {ccy}  median {v['basis_median_bps']:+.1f}bp  "
                      f"spread {v['basis_spread_bps']:.1f}bp  "
                      f"across {v['venue_count']} venues")
            else:
                names = ", ".join(e["venue"] for e in v["venues"])
                print(f"      {ccy}  {v['venue_count']} venue "
                      f"({names}) -- no median")
    if "corridors" in snap:
        for k, v in sorted(snap["corridors"].items()):
            print(f"    corridor   : {k} -- {len(v['sizes'])} sizes @ {v['ts'][:16]}Z")
    if "providers" in snap:
        for k, v in sorted(snap["providers"].items()):
            print(f"    panel      : {k} -- {len(v['sizes'])} sizes @ {v['ts_utc'][:16]}Z")
    if missing:
        # Not an error: absent means "no rows collected", which is a real and
        # honest state. Printed so it is visible in the workflow log.
        print(f"    [note] no rows for: {', '.join(missing)}")
    if not present:
        print("    [note] every source CSV was missing or empty")


if __name__ == "__main__":
    main()
