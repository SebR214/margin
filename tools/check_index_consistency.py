#!/usr/bin/env python3
"""Does every country's chart agree with its own headline number?

SEB-60: `data/index_latest.json` carries two figures per country --
`index_pct`, the published "what a dollar costs" headline, and `spark`, the
trend a reader's eye follows into that headline. They are meant to be the same
measurement at two grain sizes. Before this check existed they were computed
by two independent passes over the source rows -- one keyed to the single
newest hour, the other to a same-day median -- and 37 of 48 countries showed a
chart whose last point contradicted the number printed next to it.

`tools/emit_countries.py` now builds `spark`'s newest point directly from
`index_pct`, so the two cannot disagree by construction. This is the guard
that makes that fact checkable instead of asserted: it reads the file already
written and fails loudly if any country's last point and headline ever part
ways again -- from a future edit to the emitter, not from this check trying to
recompute either figure itself.

Exit 0 = every country's spark[-1] equals its index_pct. Exit 1 = any
disagree, or the file is unreadable, with every mismatch on stderr.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_LATEST = os.path.join(HERE, "data", "index_latest.json")


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


def main():
    if not os.path.exists(INDEX_LATEST):
        print(f"  [error] {INDEX_LATEST} does not exist", file=sys.stderr)
        sys.exit(1)
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
        sys.exit(1)
    print(f"  index consistency ok -- 0 of {n} countries disagree")


if __name__ == "__main__":
    main()
