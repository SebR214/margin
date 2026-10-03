#!/usr/bin/env python3
"""
Proves the history layer ("reported, not observed", data/history/) never leaks
into the live layer: the index, a published price, the observed series
(data/basis.csv, samples.csv, p2p_basis.csv, ...) or the unbroken-hours count.

    python3 tools/check_history_isolation.py

Exit 0 = isolated. Exit 1 = any finding, each printed on stderr.

Four proofs:
  1. STATIC  no python file other than the history tool and this check names
             the history directory, its files or its collector module (grep +
             AST import analysis).
  2. GLOBS   no emitter/collector walks data/ recursively, and the plain
             `data/*.csv` globs the emitters use (manifest, bundle) cannot
             match a history file.
  3. DYNAMIC unbroken_hours() is run with every file open recorded; none is
             under data/history/, and its inputs are only the two observed
             delivery files.
  4. DATA    every history row carries the label and a named source, no row is
             empty; and the label appears in none of the observed files.
The pre-existing daily layer data/basis_history.csv is a different file with a
different reader (tools/emit_countries.py, a country-page line); this check
also pins that it stays out of the index/price/unbroken-hours code.
"""

import ast
import builtins
import csv
import glob
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST = os.path.join(DATA, "history")
LABEL = "reported, not observed"

# Only these may mention the history layer.
HISTORY_WRITERS = {"tools/backfill_history.py", "tools/check_history_isolation.py"}
HISTORY_TOKENS = [
    re.compile(r"data/history"),
    re.compile(r"""(DATA|["']data["'])\s*,\s*["']history["']"""),   # os.path.join(DATA, "history")
    re.compile(r"candles_[a-z]+_(1h|1d)"),
    re.compile(r"official_fx_daily|parallel_dollar_daily"),
]
HISTORY_MODULES = {"backfill_history"}

# The old daily layer (basis_history.csv): readers allowed. Everything that
# builds the index, a price or the unbroken-hours count is NOT on this list.
BASIS_HISTORY_READERS = {
    "tools/emit_countries.py",     # trailing history line on a country page
    "tools/backfill_basis.py",     # its own writer
    "tools/ask_backend.py",        # table description for the Q&A tool
    "tools/serve_common.py",       # table allow-list for the API
    "collector_basis.py",          # comment only (names the file)
    "tools/emit_weekly.py",         # docstring only: says it does NOT fall back to it
}

# Modules that make the live layer: nothing here may recurse into data/.
LIVE_PREFIXES = ("collector", "tools/emit_", "tools/check_delivery", "tools/check_freshness")
# a recursive walk, or a listing of the data/ root itself (subdirs such as
# data/receipts or data/weekly are listed by their own emitters and are fine)
RECURSIVE = re.compile(r"os\.walk|\.rglob\(|glob\([^)]*\*\*|"
                       r"(?:listdir|scandir)\(\s*(?:DATA|DATA_DIR|[\"']data[\"']|"
                       r"os\.path\.join\(ROOT,\s*[\"']data[\"']\))\s*\)")

problems = []


def fail(msg):
    problems.append(msg)


def py_files():
    out = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "vendor", ".claude", "w", "data")]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(base, f), ROOT))
    return sorted(out)


def static_checks():
    for rel in py_files():
        src = open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read()
        if rel not in HISTORY_WRITERS:
            for pat in HISTORY_TOKENS:
                if pat.search(src):
                    fail(f"STATIC {rel}: names the history layer ({pat.pattern})")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""] + [a.name for a in node.names]
                for m in mods:
                    if m.split(".")[-1] in HISTORY_MODULES:
                        fail(f"STATIC {rel}: imports the history collector ({m})")
        if "basis_history" in src and rel not in BASIS_HISTORY_READERS \
                and rel not in HISTORY_WRITERS:
            fail(f"STATIC {rel}: reads data/basis_history.csv but is not an allowed reader")
        if rel.startswith(LIVE_PREFIXES) and RECURSIVE.search(src):
            hits = sorted({m.group(0) for m in RECURSIVE.finditer(src)})
            fail(f"GLOBS {rel}: directory walk in a live-layer module {hits}; "
                 "it could pick up data/history/")


def glob_checks():
    for pattern in ("*.csv", "*.json"):
        got = glob.glob(os.path.join(DATA, pattern))
        bad = [g for g in got if os.sep + "history" + os.sep in g]
        if bad:
            fail(f"GLOBS data/{pattern} matches history files: {bad[:3]}")


def dynamic_check():
    path = os.path.join(ROOT, "tools", "emit_machine_room_meters.py")
    spec = importlib.util.spec_from_file_location("emr_audit", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    spec.loader.exec_module(mod)
    opened = []
    real_open = builtins.open

    def spy(file, *a, **k):
        opened.append(os.path.abspath(str(file)))
        return real_open(file, *a, **k)

    builtins.open = spy
    try:
        mod.unbroken_hours()
    finally:
        builtins.open = real_open
    data_opened = sorted({os.path.relpath(p, ROOT) for p in opened if p.startswith(DATA)})
    if any(p.startswith(os.path.join("data", "history")) for p in data_opened):
        fail(f"DYNAMIC unbroken_hours() opened a history file: {data_opened}")
    expected = {os.path.join("data", n) for n in mod.DELIVERY_FILES}
    extra = set(data_opened) - expected
    if extra:
        fail(f"DYNAMIC unbroken_hours() opened files outside its delivery inputs: {sorted(extra)}")
    return data_opened


def data_checks():
    files = sorted(glob.glob(os.path.join(HIST, "*.csv")))
    if not files:
        fail("DATA no history files found under data/history/")
    rows_total = 0
    for f in files:
        rel = os.path.relpath(f, ROOT)
        with open(f, newline="") as fh:
            rd = csv.DictReader(fh)
            if not rd.fieldnames or "label" not in rd.fieldnames or "source" not in rd.fieldnames:
                fail(f"DATA {rel}: header lacks label/source")
                continue
            for i, r in enumerate(rd, 2):
                rows_total += 1
                if r["label"] != LABEL:
                    fail(f"DATA {rel}:{i}: label is {r['label']!r}")
                    break
                if not r["source"].strip():
                    fail(f"DATA {rel}:{i}: no source")
                    break
                if any(v in (None, "") for v in r.values()):
                    fail(f"DATA {rel}:{i}: empty field (rows are never filled)")
                    break
    # the label never appears in an observed file
    for f in glob.glob(os.path.join(DATA, "*.csv")):
        with open(f, errors="replace") as fh:
            for line in fh:
                if LABEL in line:
                    fail(f"DATA {os.path.relpath(f, ROOT)}: carries the history label")
                    break
    return len(files), rows_total


def main():
    static_checks()
    glob_checks()
    opened = dynamic_check()
    nfiles, nrows = data_checks()
    if problems:
        for p in problems:
            print("FAIL " + p, file=sys.stderr)
        sys.exit(1)
    print(f"history isolation OK: {nfiles} history files, {nrows} rows carry the label and a "
          f"source; unbroken_hours() read only {opened}; no live-layer module names or "
          f"walks data/history/")


if __name__ == "__main__":
    main()
