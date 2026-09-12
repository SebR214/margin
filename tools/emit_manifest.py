#!/usr/bin/env python3
"""Manifest of every file in data/: data/manifest_latest.json.

The rest of the site tells a reader what the market is doing. This tells a
reader what the site itself is reading from -- every top-level CSV, what its
columns are, how many rows it holds, and the date range it covers; the six
regenerated snapshot files by path, size and top-level keys; and one grouped
entry for data/countries/ rather than sixty near-identical rows. A stranger
checking the site should be able to see, from one file, that the numbers on
every other page trace back to something real on disk.

Derived, never authoritative -- including its own clock. `as_of_utc` is the
newest first-column value found across the CSVs, not the time this script
ran: an unchanged dataset regenerates a byte-identical manifest, which keeps
the collector's "nothing staged" branch reachable, same as emit_latest.py.

A CSV's first column is its timestamp, but the header name is not uniform
(`ts_utc`, `ts`, or `date` all appear) -- this reads whichever name is
actually there rather than assuming one. Row count is lines minus the header,
matching what a reader doing `wc -l` themselves would get. A missing or
empty CSV still gets an entry with rows: 0 -- an empty file is still a file a
stranger can check, never a row that silently disappears from the page.

Stdlib only. Exits non-zero only if it cannot write the output file.
Usage: python3 tools/emit_manifest.py
"""

import csv
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "manifest_latest.json")
COUNTRIES_DIR = os.path.join(DATA, "countries")

# Regenerated every collector run, hold no history -- byte size and top-level
# keys only, never a row count. Order matches the issue spec.
SNAPSHOT_FILES = [
    "latest.json", "crosses_latest.json", "index_latest.json",
    "providers_latest.json", "price_changes_latest.json", "agent_status.json",
]


def parse_ts(s):
    """ISO string (date-only or full timestamp) -> aware datetime, or None."""
    try:
        t = dt.datetime.fromisoformat((s or "").strip())
    except (TypeError, ValueError):
        return None
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t


def csv_entry(path):
    """One manifest row for a top-level CSV: columns, row count, date range."""
    rel = os.path.relpath(path, HERE).replace(os.sep, "/")
    entry = {
        "kind": "csv",
        "path": rel,
        "columns": [],
        "rows": 0,
        "date_column": None,
        "date_range": {"from": None, "to": None},
    }
    if not os.path.exists(path):
        return entry

    # Row count matches `wc -l` minus the header line -- not a parsed CSV row
    # count -- so it agrees with what anyone checking the raw file would see.
    with open(path, newline="") as f:
        line_count = sum(1 for _ in f)
    entry["rows"] = max(0, line_count - 1)

    try:
        with open(path, newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return entry
            entry["columns"] = header
            entry["date_column"] = header[0]
            first_row, last_row = None, None
            for row in reader:
                if not row:
                    continue
                if first_row is None:
                    first_row = row
                last_row = row
            if first_row is not None:
                entry["date_range"]["from"] = first_row[0]
            if last_row is not None:
                entry["date_range"]["to"] = last_row[0]
    except (OSError, csv.Error, UnicodeDecodeError):
        pass
    return entry


def snapshot_entry(name):
    """One manifest row for a regenerated top-level JSON file: size + keys."""
    path = os.path.join(DATA, name)
    entry = {"kind": "snapshot", "path": "data/" + name, "bytes": 0, "columns": []}
    if not os.path.exists(path):
        return entry
    entry["bytes"] = os.path.getsize(path)
    try:
        with open(path) as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            entry["columns"] = sorted(doc.keys())
    except (OSError, ValueError):
        pass
    return entry


def countries_entry():
    """One grouped row for data/countries/: file count + the shared key list."""
    files = sorted(glob.glob(os.path.join(COUNTRIES_DIR, "*.json")))
    entry = {
        "kind": "countries",
        "path": "data/countries/",
        "file_count": len(files),
        "columns": [],
    }
    if files:
        try:
            with open(files[0]) as f:
                doc = json.load(f)
            if isinstance(doc, dict):
                entry["columns"] = sorted(doc.keys())
        except (OSError, ValueError):
            pass
    return entry


def build():
    csv_paths = sorted(glob.glob(os.path.join(DATA, "*.csv")))
    csv_entries = [csv_entry(p) for p in csv_paths]

    stamps = []
    for e in csv_entries:
        t = parse_ts(e["date_range"]["to"])
        if t is not None:
            stamps.append(t)

    files = list(csv_entries)
    files += [snapshot_entry(name) for name in SNAPSHOT_FILES]
    files.append(countries_entry())

    manifest = {"files": files}
    if stamps:
        manifest["as_of_utc"] = max(stamps).isoformat()
    return manifest


def main():
    manifest = build()
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        # The ONLY fatal case: consumers would otherwise keep reading a stale
        # manifest with nothing to tell them it stopped being regenerated.
        print(f"  [error] cannot write {OUT}: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  wrote {OUT}: {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
