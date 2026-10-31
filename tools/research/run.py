#!/usr/bin/env python3
"""Every Research page is generated here, none by hand (SEB-423 step 3). Plain code, no model.

Each piece is a script in tools/research/ with a build() that returns the page's JSON document, written to data/research/<id>.json.
Two kinds of piece. The live ones read files that every collection run rewrites (data/index_hourly.csv, data/source_pairs.json), so they are
rebuilt on every run: a stored page file must match its inputs at every commit, or the claims audit (tools/audit_claims.py) fails it. The
yearly premium page (tools/research_capital_controls.py, from the history files) is rebuilt on the first run of each UTC month, noted in the
months file as "yearly_built_month", so on the 1st it re-runs and its "as of" line moves. A piece that fails stops the run with a non-zero
exit; nothing is written for it.

    python3 tools/research/run.py              # rebuild the pieces that are due
    python3 tools/research/run.py --force      # rebuild all
    python3 tools/research/run.py --self-test
"""
import datetime as dt
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(ROOT, "data", "research")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

# id -> module in tools/research/. Add a piece here and it is regenerated with the others.
PIECES = ["capital_controls_months", "source_pairs"]


def today_month():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")


def due(piece_id, force, month):
    p = os.path.join(OUT_DIR, piece_id + ".json")
    if force or not os.path.exists(p):
        return True
    try:
        return json.load(open(p)).get("built_month") != month
    except ValueError:
        return True


def run(force=False, month=None):
    month = month or today_month()
    built = []
    for pid in PIECES:
        mod = importlib.import_module(pid)
        old = {}
        try:
            old = json.load(open(os.path.join(OUT_DIR, pid + ".json")))
        except (OSError, ValueError):
            pass
        if pid == "capital_controls_months" and (force or old.get("yearly_built_month") != month):
            mod.rebuild_yearly()        # the yearly page re-runs from the history files on the first run of the month
            yearly = month
        else:
            yearly = old.get("yearly_built_month")
        doc = mod.build()
        doc["built_month"] = month
        if pid == "capital_controls_months":
            doc["yearly_built_month"] = yearly
        os.makedirs(OUT_DIR, exist_ok=True)
        tmp = os.path.join(OUT_DIR, pid + ".json.tmp")
        with open(tmp, "w") as f:
            json.dump(doc, f, separators=(",", ":"))
            f.write("\n")
        os.replace(tmp, os.path.join(OUT_DIR, pid + ".json"))
        built.append(pid)
    return built


def self_test():
    import tempfile
    global OUT_DIR
    old = OUT_DIR
    OUT_DIR = tempfile.mkdtemp()
    try:
        assert due("x", False, "2026-10")
        json.dump({"built_month": "2026-10"}, open(os.path.join(OUT_DIR, "x.json"), "w"))
        assert not due("x", False, "2026-10") and due("x", False, "2026-11") and due("x", True, "2026-10")
    finally:
        OUT_DIR = old
    for pid in PIECES:
        importlib.import_module(pid).self_test()
    print("research run self-test ok")
    return 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    built = run(force="--force" in sys.argv)
    print("research pages rebuilt: %s" % (", ".join(built) if built else "none due"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
