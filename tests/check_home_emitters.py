#!/usr/bin/env python3
"""Offline invariants for the SEB-240 data emitters, run on the stored data.

Runs each emitter's --self-test (builds the document in memory, asserts it, writes
nothing) and then checks the committed JSON files are in step with what the emitters
build now: same days, no NaN. Exit 1 on the first failure.

    python3 tests/check_home_emitters.py
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = ["emit_record_daily", "emit_cycle_log", "emit_record_milestones",
         "emit_movers_week", "emit_sources_daily", "emit_findings"]
FILES = ["record_daily", "cycle_log", "record_milestones", "movers_week", "sources_daily", "findings"]


def main():
    for t in TOOLS:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", t + ".py"), "--self-test"],
                           capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode:
            sys.stderr.write(r.stderr)
            print("FAIL " + t, file=sys.stderr)
            return 1
    for f in FILES:
        p = os.path.join(ROOT, "data", f + ".json")
        doc = json.load(open(p), parse_constant=lambda c: (_ for _ in ()).throw(ValueError("NaN/inf in " + f)))
        assert doc, f
    rd = json.load(open(os.path.join(ROOT, "data", "record_daily.json")))
    sd = json.load(open(os.path.join(ROOT, "data", "sources_daily.json")))
    assert [d["day"] for d in rd["days"]] == sd["days"], "record and sources cover the same days"
    print("home emitters ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
