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
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "latest.json")

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


def main():
    snap = build()
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(snap, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        # The ONLY fatal case: consumers would otherwise keep reading a stale
        # snapshot with nothing to tell them it stopped being regenerated.
        print(f"  [error] cannot write {OUT}: {e}", file=sys.stderr)
        sys.exit(1)

    present = [k for k in ("basis", "corridors", "providers") if k in snap]
    missing = [k for k in ("basis", "corridors", "providers") if k not in snap]
    print(f"  wrote {os.path.relpath(OUT, HERE)} "
          f"({os.path.getsize(OUT):,} bytes)")
    if "as_of_utc" in snap:
        print(f"    as of      : {snap['as_of_utc']} (newest source row)")
    if "basis" in snap:
        print(f"    basis      : {len(snap['basis'])} venues")
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
