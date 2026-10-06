#!/usr/bin/env python3
"""Merge copy/*.json into copy.json, the one file the pages fetch.

The words live in copy/<page>.json, one file per page (copy/shared.json holds
the brand, nav, chart and other sitewide keys). Pull requests edit only those
files, so two PRs on different pages never touch the same file and cannot
conflict. copy.json is generated from them: the pages still fetch ./copy.json,
and it stays committed because the site is served statically from main. After
a merge that touches copy/, the `copy-build` workflow rebuilds and commits it.
Do not edit copy.json by hand.

The merge is deterministic: top-level keys come out in ORDER below (any key not
listed follows, in file-name order), formatted with two-space indent, real
unicode, one trailing newline.

Usage:
  python3 tools/build_copy.py           # write copy.json
  python3 tools/build_copy.py --check   # exit 1 if copy.json is not the merge of copy/
"""

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "copy")
OUT = os.path.join(HERE, "copy.json")

# The order copy.json has always had. Only a new top-level key needs no entry here.
ORDER = ["brand", "shared", "home", "nav", "chart", "index", "corridor", "receipt", "receiptCorridor",
         "receiptPriceChange", "receiptMeter", "receiptProvider", "receiptDelivery", "country", "howItWorks",
         "machineRoom", "redirects", "sendingMoney", "receiptCrossover", "tape", "receiptBasis", "countries",
         "routeData", "homeData", "sourcesData", "countryData", "findingData"]


def dump(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def merge(parts):
    """parts: {file name: dict}. Returns one dict; a key in two files is an error."""
    merged, owner = {}, {}
    for name in sorted(parts):
        for k, v in parts[name].items():
            if k in merged:
                raise SystemExit("copy: top-level key %r is in both %s and %s" % (k, owner[k], name))
            merged[k], owner[k] = v, name
    rank = {k: i for i, k in enumerate(ORDER)}
    return {k: merged[k] for k in sorted(merged, key=lambda k: (rank.get(k, len(rank)), owner[k], k))}


def load(src=SRC):
    parts = {}
    for p in sorted(glob.glob(os.path.join(src, "*.json"))):
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            raise SystemExit("%s: must be a JSON object" % p)
        parts[os.path.basename(p)] = doc
    return parts


def main():
    text = dump(merge(load()))
    if "--check" in sys.argv[1:]:
        try:
            have = open(OUT, encoding="utf-8").read()
        except OSError:
            have = ""
        if json.loads(have or "{}") != json.loads(text):
            print("copy.json is not the merge of copy/*.json. Run: python3 tools/build_copy.py")
            return 1
        print("copy.json matches copy/*.json")
        return 0
    old = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else None
    if old != text:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote copy.json")
    else:
        print("copy.json already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
