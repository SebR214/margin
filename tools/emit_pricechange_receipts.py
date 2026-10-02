#!/usr/bin/env python3
"""The receipt behind a price change: data/pricechange_receipts/<key>.json (SEB-187).

`data/price_changes_latest.json` says a provider's price moved by X on a day.
This says WHY: the individual hourly readings -- this provider's own, and
every other provider's it was checked against -- that the pairwise-unanimity
test (METHODOLOGY, ROADMAP P0.06) used to make that call, traced back far
enough that a stranger can redo the arithmetic themselves.

One receipt per confirmed row, keyed by corridor+size+provider+day, same key
`tools/emit_price_changes.py` uses to dedupe `data/price_changes.csv`. Every
top-level number a receipt states (old_cost_pct, new_cost_pct, move_pct,
n_agree, n_panel) is read straight from that row -- nothing new to collect.
What this file adds is the evidence underneath: the raw hourly cost_bps rows
in `data/providers.csv` (or whichever sibling the row's own `source_file`
names) that fed the two medians the row's own arithmetic runs on.

THE ONE WRINKLE: WHICH PROVIDERS COUNTED AS THE COMPARISON SET.

emit_price_changes.py's panel_events() only counts a provider as part of the
comparison set ("core", below) if it was quoted at every single hourly
timestamp the corridor+size has EVER recorded -- as of whenever that
particular run happened to execute. That set is not itself stored anywhere;
only the row's own n_agree/n_panel counts are. Because the panel CSVs keep
growing hour over hour, recomputing "core" from TODAY's full file can
retroactively shrink it for an old day, if some provider has since missed
even one later hour -- a provider correctly counted when the row was
confirmed can look, from today's vantage point, like it was never fully
present. Readings for a corridor+size are rebuilt once per candidate cutoff
date, walking forward a few weeks from the change day, and the first cutoff
whose own recomputed old_cost_pct/new_cost_pct/move_pct/prev_day_cost_pct/
n_agree/n_panel reproduce the row's stored values exactly is kept as that
row's evidence. This is evidence assembly, not the detection logic itself --
the thresholds are read, never redefined, and emit_price_changes.py's own
file is neither imported nor changed.

A row whose stored numbers cannot be reproduced by any cutoff in that window
gets no receipt file -- every one of the 745 rows on record today resolves
within the window, but the window is finite on purpose, so a future row that
genuinely can't be reconstructed is not hidden: it is named on stderr and
counted in the summary, and a reader who clicks it sees the overlay's own
honest "could not be read" state, same as any other missing file on this
site.

Append-only, same as price_changes.csv: a receipt already on disk is never
rewritten. Stdlib only. No wall clock -- nothing here is timestamped by this
run, only by the row's own `day`/`old_day`, so an unchanged dataset
regenerates byte-identical receipts for anything not already written.

Usage: python3 tools/emit_pricechange_receipts.py
"""

import csv
import datetime as dt
import itertools
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
CHANGES_JSON = os.path.join(DATA, "price_changes_latest.json")
OUT_DIR = os.path.join(DATA, "pricechange_receipts")

# Mirrors emit_price_changes.py's own constants. Read-only -- this file does
# not change what counts as a confirmed move, only explains it.
THRESHOLD_PCT = 0.02
MIN_READINGS = 6

# How many days forward of the change day to try reconstructing the panel
# from, before giving up on that row. See the module docstring's "ONE
# WRINKLE" -- in practice nearly every row resolves within the first day or
# two; this window only exists to cover the slower-to-confirm ones.
SEARCH_WINDOW_DAYS = 21

EPSILON = 1e-6  # float round-trip slack, not a tolerance for being wrong


def num(raw):
    if isinstance(raw, float):
        return raw if raw == raw else None
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def safe_key_part(s):
    s = re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")
    return s or "unknown"


def receipt_filename(row):
    corridor = row["corridor"].replace("->", "-")
    return f"{corridor}_{row['size']}_{safe_key_part(row['provider'])}_{row['day']}.json"


# ------------------------------------------------------------- panel reading
def panel_readings(rows, size, cutoff_date):
    """The comparison set and readings panel_events() would have built,
    using only rows at or before `cutoff_date` -- a stand-in for however
    much history the panel actually held the day this row was confirmed.
    """
    sub = [r for r in rows
           if r.get("notional_src") == size and r.get("source_ok") == "True"
           and r.get("ts_utc", "")[:10] <= cutoff_date
           and num(r.get("cost_bps")) is not None]
    stamps = sorted({r["ts_utc"] for r in sub})
    if not stamps:
        return [], {}, {}

    seen = {}
    for r in sub:
        seen[r["provider"]] = seen.get(r["provider"], 0) + 1
    core = sorted(p for p, n in seen.items() if n == len(stamps))

    by_stamp = {}
    for r in sub:
        if r["provider"] in core:
            by_stamp.setdefault(r["ts_utc"], {})[r["provider"]] = num(r["cost_bps"])

    own_day, pair_day = {}, {}
    for ts in stamps:
        quotes = by_stamp.get(ts, {})
        day = ts[:10]
        for p in core:
            if p in quotes:
                own_day.setdefault((p, day), []).append((ts, quotes[p]))
        for a, b in itertools.permutations(core, 2):
            if a in quotes and b in quotes:
                pair_day.setdefault((a, b, day), []).append((ts, quotes[a] - quotes[b]))
    return core, own_day, pair_day


def try_reconstruct(row, core, own_day, pair_day):
    """Replays the row's own arithmetic against one candidate panel. Returns
    the built receipt's evidence/computation if every stored number comes
    back exactly, else None.
    """
    provider = row["provider"]
    old_day, new_day = row["old_day"], row["day"]
    if provider not in core:
        return None

    own_old = own_day.get((provider, old_day)) or []
    own_new = own_day.get((provider, new_day)) or []
    if not own_old or not own_new:
        return None

    peer_moves, peer_readings = {}, {}
    for q in core:
        if q == provider:
            continue
        v0 = pair_day.get((provider, q, old_day)) or []
        v1 = pair_day.get((provider, q, new_day)) or []
        if len(v0) < MIN_READINGS or len(v1) < MIN_READINGS:
            continue
        peer_moves[q] = statistics.median(v for _, v in v1) - statistics.median(v for _, v in v0)
        peer_readings[q] = {
            "old_day": [{"ts_utc": ts, "cost_bps": v} for ts, v in (own_day.get((q, old_day)) or [])],
            "new_day": [{"ts_utc": ts, "cost_bps": v} for ts, v in (own_day.get((q, new_day)) or [])],
        }
    if not peer_moves:
        return None

    # Unrounded medians first -- old_cost_pct is derived from these two
    # directly (same order emit_price_changes.py itself uses), not from the
    # already-rounded move_pct/new_cost_pct below, which would round twice
    # and occasionally land a cent off.
    now = statistics.median(v for _, v in own_new) / 100.0
    mv = statistics.median(peer_moves.values()) / 100.0
    move_pct = round(mv, 4)
    new_cost_pct = round(now, 4)
    old_cost_pct = round(now - mv, 4)
    prev_day_cost_pct = round(statistics.median(v for _, v in own_old) / 100.0, 4)

    stored = {
        "old_cost_pct": num(row["old_cost_pct"]),
        "new_cost_pct": num(row["new_cost_pct"]),
        "move_pct": num(row["move_pct"]),
        "n_agree": str(row.get("n_agree")),
        "n_panel": str(row.get("n_panel")),
        "prev_day_cost_pct": num(row["prev_day_cost_pct"]),
    }
    recomputed = {
        "move_pct": move_pct, "new_cost_pct": new_cost_pct,
        "old_cost_pct": old_cost_pct, "prev_day_cost_pct": prev_day_cost_pct,
        "n_agree": str(len(peer_moves)), "n_panel": str(len(core)),
    }
    for k in ("move_pct", "new_cost_pct", "old_cost_pct", "prev_day_cost_pct"):
        if abs(stored[k] - recomputed[k]) > EPSILON:
            return None
    if stored["n_agree"] != recomputed["n_agree"] or stored["n_panel"] != recomputed["n_panel"]:
        return None

    return {
        "own_old": own_old, "own_new": own_new,
        "peer_moves": peer_moves, "peer_readings": peer_readings,
        "core": core, "recomputed": recomputed,
    }


def build_receipt(row, result, cutoff_date):
    own_old, own_new = result["own_old"], result["own_new"]
    source_file = row.get("source_file")
    source_files = sorted(set(filter(None, [
        source_file, "data/price_changes.csv", "data/price_changes_latest.json"])))

    return {
        "corridor": row["corridor"],
        "size": row["size"],
        "provider": row["provider"],
        "day": row["day"],
        "old_day": row["old_day"],
        "ts_utc": row["ts_utc"],
        "computed_at": row.get("computed_at"),
        "kind": row.get("kind"),
        "route_words": row.get("route_words"),
        "amount_words": row.get("amount_words"),
        "stored": {
            "old_cost_pct": num(row["old_cost_pct"]),
            "new_cost_pct": num(row["new_cost_pct"]),
            "move_pct": num(row["move_pct"]),
            "n_agree": row.get("n_agree"),
            "n_panel": row.get("n_panel"),
            "prev_day_cost_pct": num(row["prev_day_cost_pct"]),
        },
        "evidence": {
            "panel": result["core"],
            "panel_reconstructed_through": cutoff_date,
            "own_readings": {
                "old_day": [{"ts_utc": ts, "cost_bps": v} for ts, v in own_old],
                "new_day": [{"ts_utc": ts, "cost_bps": v} for ts, v in own_new],
            },
            "peer_readings": result["peer_readings"],
            "source_file": source_file,
        },
        "computation": {
            "threshold_pct": THRESHOLD_PCT,
            "min_readings": MIN_READINGS,
            "per_peer_move_pct": {q: round(v / 100.0, 4) for q, v in result["peer_moves"].items()},
            **result["recomputed"],
        },
        "source_files": source_files,
    }


def main():
    if not os.path.exists(CHANGES_JSON):
        print("  no data/price_changes_latest.json yet -- nothing to explain")
        return 0

    with open(CHANGES_JSON) as f:
        changes = (json.load(f).get("changes")) or []

    os.makedirs(OUT_DIR, exist_ok=True)
    existing = set(os.listdir(OUT_DIR))

    fresh = []
    seen_names = set()
    for row in changes:
        name = receipt_filename(row)
        if name in existing or name in seen_names:
            continue
        seen_names.add(name)
        fresh.append((name, row))

    file_cache = {}
    panel_cache = {}

    def rows_for(source_file):
        if source_file not in file_cache:
            file_cache[source_file] = read_rows(os.path.join(HERE, source_file))
        return file_cache[source_file]

    def panel_for(source_file, size, cutoff_date):
        key = (source_file, size, cutoff_date)
        if key not in panel_cache:
            panel_cache[key] = panel_readings(rows_for(source_file), size, cutoff_date)
        return panel_cache[key]

    written, unresolved = 0, []
    for name, row in fresh:
        source_file = row.get("source_file")
        if not source_file:
            unresolved.append((name, "no source_file on the row"))
            continue
        new_day = dt.date.fromisoformat(row["day"])
        receipt = None
        for cd in range(SEARCH_WINDOW_DAYS + 1):
            cutoff_date = (new_day + dt.timedelta(days=cd)).isoformat()
            core, own_day, pair_day = panel_for(source_file, row["size"], cutoff_date)
            result = try_reconstruct(row, core, own_day, pair_day)
            if result is not None:
                receipt = build_receipt(row, result, cutoff_date)
                break
        if receipt is None:
            unresolved.append((name, "no panel within the search window reproduces the stored numbers"))
            continue
        with open(os.path.join(OUT_DIR, name), "w") as f:
            json.dump(receipt, f, indent=2, sort_keys=True)
            f.write("\n")
        written += 1

    print(f"  wrote {written} new receipts -> data/pricechange_receipts/ "
          f"({len(existing)} already there)")
    if unresolved:
        print(f"  {len(unresolved)} row(s) could not be explained -- the comparison panel "
              f"at confirmation time can no longer be reconstructed. Shown, not hidden:",
              file=sys.stderr)
        for name, reason in unresolved:
            print(f"    [no receipt] {name}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
