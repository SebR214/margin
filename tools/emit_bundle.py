#!/usr/bin/env python3
"""The whole site, compacted into one bundle a browser can query directly:
data/bundle/*.parquet plus data/bundle/manifest.json.

This is what SEB-40 asked for -- everything the site publishes, in a form
DuckDB-WASM can load client-side, so charts and Ask can run in the page
instead of hitting the server for every query. Loading it into the browser is
out of scope here (see U2, U4); this only has to produce the files.

One parquet file per top-level CSV in data/, table name == file stem, columns
and types exactly as duckdb infers them from the CSV -- no renaming, no
reshaping. Plus two tables built from data/countries/*.json, the one part of
"everything the site publishes" that isn't already a CSV:

  country_latest   one row per currency, every scalar field the country file
                    carries (nested fields like `denominator` and
                    `instrument_check` stay structured, not flattened to
                    strings -- parquet and DuckDB both handle nested columns).
  country_history  the `history` array unnested to one row per
                    (ccy, date) -- what a chart actually iterates over.

Chose parquet-plus-manifest over a single margin.duckdb file on measured size:
the same content came to about 6.8 MB as one duckdb database and about 1.3 MB
as a parquet set, because parquet's per-column encoding compresses this data
far better than duckdb's own storage format does at this scale. Parquet is
also the format DuckDB-WASM's own docs point at for exactly this browser-query
use case, so the smaller choice and the better-supported one are the same
choice.

Derived, never authoritative -- like every snapshot in this repo, this reads
data/ and writes an output; it is not a new source of truth. Not silently
truncated: if the bundle ever exceeds BUNDLE_MAX_BYTES this still writes
every table (so the real size is on disk to inspect) and then exits non-zero,
loudly, instead of dropping rows to fit.

Needs duckdb -- see requirements.txt. The one dependency in this repo besides
requests, because writing real parquet without a real parquet writer would
mean re-implementing one.

Usage: python3 tools/emit_bundle.py
"""

import datetime as dt
import glob
import json
import os
import sys

import duckdb

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
BUNDLE_DIR = os.path.join(DATA, "bundle")
COUNTRIES_DIR = os.path.join(DATA, "countries")
MANIFEST_OUT = os.path.join(BUNDLE_DIR, "manifest.json")

# "Target: under 15 MB" -- checked against the plain decimal MB, the smaller
# (stricter) of the two common readings, so a bundle that "fits" here fits
# either way.
BUNDLE_MAX_BYTES = 15_000_000


def csv_tables(con):
    """One table per top-level CSV, name == file stem, types as duckdb infers
    them. strict_mode=false: several of these CSVs carry an `error` column
    where writers quote correctly but the field count still varies row to
    row (e.g. offramp_snapshots.csv), which duckdb's dialect sniffer treats
    as fatal unless told not to."""
    names = []
    for path in sorted(glob.glob(os.path.join(DATA, "*.csv"))):
        name = os.path.splitext(os.path.basename(path))[0]
        con.execute(
            f'CREATE TABLE "{name}" AS '
            f"SELECT * FROM read_csv_auto(?, header=true, strict_mode=false)",
            [path],
        )
        names.append(name)
    return names


def country_tables(con):
    """country_latest (one row per currency, nested fields stay structured)
    and country_history (the `history` array, unnested to one row per
    ccy/date -- what a chart iterates over)."""
    pattern = os.path.join(COUNTRIES_DIR, "*.json")
    con.execute(
        f"CREATE TABLE country_raw AS "
        f"SELECT * FROM read_json_auto('{pattern}', union_by_name=true)"
    )
    con.execute("CREATE TABLE country_latest AS SELECT * EXCLUDE (history) FROM country_raw")
    con.execute(
        "CREATE TABLE country_history AS "
        "SELECT ccy, h.date AS date, h.index_pct AS index_pct, "
        "h.n AS n, h.source AS source "
        "FROM country_raw, UNNEST(history) AS t(h)"
    )
    con.execute("DROP TABLE country_raw")
    return ["country_latest", "country_history"]


def as_of_utc(con, csv_table_names):
    """Newest timestamp across the CSV tables' first column -- same
    "derived, not measured" clock emit_manifest.py uses, so a bundle of an
    unchanged dataset reports the same as_of_utc the manifest does."""
    stamps = []
    for name in csv_table_names:
        first_col = con.execute(f'DESCRIBE "{name}"').fetchone()[0]
        row = con.execute(
            f'SELECT max(try_cast("{first_col}" AS TIMESTAMP)) FROM "{name}"'
        ).fetchone()
        if row and row[0] is not None:
            stamps.append(row[0])
    if not stamps:
        return None
    newest = max(stamps)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=dt.timezone.utc)
    return newest.isoformat()


def export(con, table_names):
    """Every table to its own parquet file in data/bundle/, wiping whatever
    parquet files were there before so a table removed from this run cannot
    leave a stale, orphaned file behind."""
    os.makedirs(BUNDLE_DIR, exist_ok=True)
    for stale in glob.glob(os.path.join(BUNDLE_DIR, "*.parquet")):
        os.remove(stale)

    tables = {}
    for name in table_names:
        rel = f"{name}.parquet"
        out_path = os.path.join(BUNDLE_DIR, rel)
        con.execute(f'COPY "{name}" TO ? (FORMAT PARQUET)', [out_path])
        columns = [row[0] for row in con.execute(f'DESCRIBE "{name}"').fetchall()]
        rows = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        tables[name] = {
            "file": rel,
            "bytes": os.path.getsize(out_path),
            "rows": rows,
            "columns": columns,
        }
    return tables


def main():
    con = duckdb.connect()
    csv_names = csv_tables(con)
    country_names = country_tables(con)
    tables = export(con, csv_names + country_names)

    manifest = {
        "as_of_utc": as_of_utc(con, csv_names),
        "total_bytes": sum(t["bytes"] for t in tables.values()),
        "tables": tables,
    }
    try:
        with open(MANIFEST_OUT, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write {MANIFEST_OUT}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  wrote {len(tables)} tables to {BUNDLE_DIR}: "
          f"{manifest['total_bytes']:,} bytes total")

    if manifest["total_bytes"] > BUNDLE_MAX_BYTES:
        # Loud, not smoothed: every table is still written above, so the
        # real size is on disk to inspect -- this never drops a row to fit.
        print(
            f"  [error] bundle is {manifest['total_bytes']:,} bytes, "
            f"over the {BUNDLE_MAX_BYTES:,}-byte target -- "
            f"trim needs a human call (oldest history first, at a stated "
            f"cutoff), not a silent drop",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
