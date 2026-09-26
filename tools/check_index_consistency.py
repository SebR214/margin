#!/usr/bin/env python3
"""Does every number shown on more than one page agree with itself?

Two checks live here, both about the same failure mode: a figure computed
twice, in two places, drifting apart from a real code difference rather
than a real change in the underlying data.

  1. Every country's chart agrees with its own headline number.

     SEB-60: `data/index_latest.json` carries two figures per country --
     `index_pct`, the published "what a dollar costs" headline, and
     `spark`, the trend a reader's eye follows into that headline. They are
     meant to be the same measurement at two grain sizes. Before this check
     existed they were computed by two independent passes over the source
     rows -- one keyed to the single newest hour, the other to a same-day
     median -- and 37 of 48 countries showed a chart whose last point
     contradicted the number printed next to it.

     `tools/emit_countries.py` now builds `spark`'s newest point directly
     from `index_pct`, so the two cannot disagree by construction. This is
     the guard that makes that fact checkable instead of asserted: it reads
     the file already written and fails loudly if any country's last point
     and headline ever part ways again -- from a future edit to the
     emitter, not from this check trying to recompute either figure itself.

  2. Every page that states the SGD->PHP headline cost -- the home page's
     hero sub and waterfall caption, fee-tiers.html's breakdown caption --
     reads it from data/corridor_window.json, ONE file written once by
     tools/bake_homepage.py, rather than recomputing the send amount, the
     stablecoin cost, the cheapest-app cost or the window a second time.
     This half of the check reads data/corridor_summary.json (the file
     corridor_window.json is itself derived from) and re-derives what each
     corridor's window row SHOULD say, then fails loudly if
     corridor_window.json on disk says anything else -- the same "prove it
     renders what the sidecar says" shape as corridor.html's own
     waterfall-reconciliation check, not a re-derivation for its own sake.

Exit 0 = every check above agrees. Exit 1 = any disagreement, or a required
file is unreadable, with every mismatch on stderr.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_LATEST = os.path.join(HERE, "data", "index_latest.json")
CORRIDOR_SUMMARY = os.path.join(HERE, "data", "corridor_summary.json")
CORRIDOR_WINDOW = os.path.join(HERE, "data", "corridor_window.json")


def mismatches(snapshot):
    """[(ccy, index_pct, spark_last)] for every country where they disagree."""
    bad = []
    for row in snapshot.get("countries", []):
        spark = row.get("spark") or []
        if not spark:
            continue                       # nothing to compare a headline against
        if spark[-1] != row.get("index_pct"):
            bad.append((row.get("ccy"), row.get("index_pct"), spark[-1]))
    return bad


def corridor_window_mismatches(summary, window):
    """[(corridor, field, expected, actual)] for every value
    data/corridor_window.json gets wrong against what data/corridor_summary.json
    says it should be -- the same rounding tools/bake_homepage.py itself uses,
    so a real rounding difference never shows up as a false failure here.
    """
    bad = []
    rung = summary.get("rung")
    for c in summary.get("corridors", []):
        corridor = c.get("corridor")
        row = window.get(corridor)
        if row is None:
            bad.append((corridor, "row", "present", "missing from corridor_window.json"))
            continue
        if rung is not None and row.get("rung") != rung:
            bad.append((corridor, "rung", rung, row.get("rung")))
        stable_bps = c.get("taker_cost_bps_median")
        if rung is not None and stable_bps is not None:
            expected = round(rung * stable_bps / 10000, 2)
            if row.get("stable_cost") != expected:
                bad.append((corridor, "stable_cost", expected, row.get("stable_cost")))
        best_bps = c.get("baseline_cost_bps_median")
        if rung is not None and best_bps is not None:
            expected = round(rung * best_bps / 10000, 2)
            if row.get("best_cost") != expected:
                bad.append((corridor, "best_cost", expected, row.get("best_cost")))
        if row.get("n_hours") != c.get("n"):
            bad.append((corridor, "n_hours", c.get("n"), row.get("n_hours")))
    return bad


def main():
    ok = True

    if not os.path.exists(INDEX_LATEST):
        print(f"  [error] {INDEX_LATEST} does not exist", file=sys.stderr)
        ok = False
    else:
        with open(INDEX_LATEST) as f:
            snapshot = json.load(f)
        n = len(snapshot.get("countries", []))
        bad = mismatches(snapshot)
        print(f"  checked {n} countries with a published figure")
        if bad:
            for ccy, headline, spark_last in bad:
                print(f"  [MISMATCH] {ccy}: index_pct={headline} spark[-1]={spark_last}",
                      file=sys.stderr)
            print(f"\n  [error] {len(bad)} of {n} countries: chart and headline disagree",
                  file=sys.stderr)
            ok = False
        else:
            print(f"  index consistency ok -- 0 of {n} countries disagree")

    if os.path.exists(CORRIDOR_SUMMARY) and os.path.exists(CORRIDOR_WINDOW):
        with open(CORRIDOR_SUMMARY) as f:
            summary = json.load(f)
        with open(CORRIDOR_WINDOW) as f:
            window = json.load(f)
        bad = corridor_window_mismatches(summary, window)
        print(f"  checked {len(summary.get('corridors', []))} corridors' shared headline figures")
        if bad:
            for corridor, field, expected, actual in bad:
                print(f"  [MISMATCH] {corridor}.{field}: corridor_summary.json implies "
                      f"{expected!r}, corridor_window.json says {actual!r}", file=sys.stderr)
            print(f"\n  [error] {len(bad)} shared-figure mismatch(es) -- "
                  f"run tools/bake_homepage.py", file=sys.stderr)
            ok = False
        else:
            print("  corridor_window.json consistency ok -- every shared figure "
                  "matches data/corridor_summary.json")
    else:
        print("  no data/corridor_summary.json + data/corridor_window.json yet -- "
              "nothing to cross-check")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
