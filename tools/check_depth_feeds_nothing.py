#!/usr/bin/env python3
"""data/depth.csv feeds nothing published until its 7 days in quarantine are over (SEB-302, depth record step 2).

    python3 tools/check_depth_feeds_nothing.py

Fails if any emitter, page script or page reads data/depth.csv, other than the collector that writes it, the report that summarises it
and this check. After QUARANTINE_ENDS the rule is lifted (a person decides what, if anything, to build on it, in a Linear spec).
"""
import datetime
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUARANTINE_ENDS = datetime.date(2026, 10, 27)
NAME = re.compile(r"(?<![A-Za-z0-9_])depth\.csv")      # data/depth.csv, not p2p_depth.csv or samples_depth.csv
ALLOWED = {"collector_depth.py", "depth_common.py", "tools/report_depth.py", "tools/check_depth_feeds_nothing.py", "tools/check_additive.py", "BACKLOG.md", "METHODOLOGY.md",
           ".github/workflows/collect.yml", ".github/workflows/checks.yml"}


def readers(root=ROOT):
    out = []
    pats = ["tools/*.py", "js/*.js", "*.html", "*.py", "css/*.css", "copy.json", "agents/*.py", ".github/workflows/*.yml"]
    for pat in pats:
        for f in glob.glob(os.path.join(root, pat)):
            rel = os.path.relpath(f, root)
            if " " in os.path.basename(f) or rel in ALLOWED:
                continue
            try:
                if NAME.search(open(f, errors="replace").read()):
                    out.append(rel)
            except OSError:
                pass
    return sorted(out)


def main(today=None):
    today = today or datetime.date.today()
    if today >= QUARANTINE_ENDS:
        print("depth.csv: the 7 days are over (%s), nothing to check" % QUARANTINE_ENDS)
        return 0
    bad = readers()
    if bad:
        print("depth.csv is in quarantine until %s and these files read it: %s" % (QUARANTINE_ENDS, ", ".join(bad)))
        return 1
    print("depth.csv feeds nothing (quarantine until %s)" % QUARANTINE_ENDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
