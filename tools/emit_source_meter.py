#!/usr/bin/env python3
"""The honest source meter -- SOURCES task 4.

Every price this site publishes this hour comes from one of three places,
and a reader should be able to see the split without reading the code:

  1. the provider's OWN published quote (data/provider_quotes.csv, via
     collector_providers.py -- see its precedence-rule docstring)
  2. a comparison feed that stands in where a provider does not publish its
     own (today, exactly one: Wise's v4/comparisons API, read by
     collector.py's fetch_baseline() into providers*.csv)
  3. the stablecoin route, priced across every venue collector_stable_venues.py
     (SOURCES task 3) reads for that corridor this hour

This script counts all three, LIVE, from data/providers_latest.json --
tools/emit_providers.py's own output, which already tags every row with
`source` ("own" / "comparison" / "measured" / "missing"). Nothing here is
typed: a provider going quiet, a comparison feed dropping a name, or a
stablecoin venue going dark all move these numbers on the next run, same as
every other computed figure on this site (DESIGN.md: "Numbers are computed
from data/, never typed").

    data/source_meter.json
    {n_own, n_comparison, n_total_quoted, comparison_feed_names,
     n_stable_venues, stable_venue_names, n_missing, as_of_utc, sentence}

`sentence` is the filled copy.json template
(shared.sourceMeterTemplate: "{n_own} of {n_total_quoted} prices this hour
quoted by the provider itself, {n_comparison} from {comparison_feed_words}
comparison feeds, stablecoins from {n_stable_venues} venues."), built the
same way tools/bake_homepage.py fills home.headlineSub -- so sending-money.html
and machine-room.html read one already-filled sentence instead of each
re-implementing the substitution.

Usage: python3 tools/emit_source_meter.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
PROVIDERS_LATEST = os.path.join(DATA, "providers_latest.json")
COPY = os.path.join(HERE, "copy.json")
OUT = os.path.join(DATA, "source_meter.json")


def build():
    if not os.path.exists(PROVIDERS_LATEST):
        return None
    with open(PROVIDERS_LATEST) as f:
        doc = json.load(f)

    n_own = n_comparison = n_missing = 0
    stable_venues = set()
    for corridor in doc.get("corridors", {}).values():
        for size in corridor.get("sizes", {}).values():
            for r in size.get("rows", []):
                src = r.get("source")
                if src == "own":
                    n_own += 1
                elif src == "comparison":
                    n_comparison += 1
                elif src == "missing":
                    n_missing += 1
                elif src == "measured":
                    v = r.get("venues")
                    if v:
                        for c in v.get("combos", []):
                            if c.get("buy_venue"):
                                stable_venues.add(c["buy_venue"])
                            if c.get("sell_venue"):
                                stable_venues.add(c["sell_venue"])

    n_total_quoted = n_own + n_comparison
    # Only one comparison feed exists in this repo today (Wise's own
    # comparisons API -- see collector.py's fetch_baseline and
    # collector_providers.py's precedence-rule docstring for why it is not
    # itself counted as "own"). Named here, not hardcoded into the sentence,
    # so a second comparison feed added later shows up automatically instead
    # of the sentence quietly becoming wrong.
    comparison_feed_names = ["Wise"] if n_comparison else []

    doc_out = {
        "n_own": n_own,
        "n_comparison": n_comparison,
        "n_total_quoted": n_total_quoted,
        "comparison_feed_names": comparison_feed_names,
        "n_missing": n_missing,
        "n_stable_venues": len(stable_venues),
        "stable_venue_names": sorted(stable_venues),
        "as_of_utc": doc.get("as_of_utc") or doc.get("computed_at"),
    }

    with open(COPY) as f:
        copy_doc = json.load(f)
    tmpl = (copy_doc.get("shared") or {}).get("sourceMeterTemplate", "")
    vals = {
        "n_own": str(n_own),
        "n_total_quoted": str(n_total_quoted),
        "n_comparison": str(n_comparison),
        "comparison_feed_words": " and ".join(comparison_feed_names) if comparison_feed_names else "no",
        "n_stable_venues": str(len(stable_venues)),
    }
    sentence = tmpl
    for k, v in vals.items():
        sentence = sentence.replace("{" + k + "}", v)
    doc_out["sentence"] = sentence
    return doc_out


def main():
    doc = build()
    if doc is None:
        print("  no data/providers_latest.json yet -- run tools/emit_providers.py first")
        sys.exit(1)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"  wrote {os.path.relpath(OUT, HERE)}: {doc['sentence']}")


if __name__ == "__main__":
    main()
