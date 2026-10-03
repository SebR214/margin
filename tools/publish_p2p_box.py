#!/usr/bin/env python3
"""The seam between the box collector's local state and the git repo
(ROADMAP item 12, SEB-202).

`collector_p2p_box.py` runs every ten minutes on the Hetzner box and writes
only to BOX_STATE_DIR (default /var/lib/margin/p2p_box) -- a staged
publish CSV and raw per-pass parquet files, both outside every git checkout
on the box. See that file's module docstring, "RAW VS PUBLISHED", for why:
~165 currencies x up to 20 ads x 2 sides every ten minutes is real data this
project is not entitled to invent away, but is also far too much for `data/`
(git, kept forever) to carry raw, and no checkout on the box is a safe place
for a long-lived file an unattended loop keeps appending to -- the agent-role
checkouts switch branches constantly and the served checkout is hard-reset by
margin-pull.timer every five minutes.

THIS FILE DOES NOT PUSH TO GIT. Every other append-only collector in this repo
reaches `main` one of two ways: the three agent roles open a PR like any other
change (BUILDER.md), or GitHub Actions' own collect.yml commits directly using
a token that lives in GitHub's infrastructure, scoped to that one audited
workflow. Neither exists for code running on the box itself -- the box's own
GitHub App token (agents/gh_token.sh) is deliberately scoped to opening pull
requests only (SEB-51, SEB-63: it cannot even cast an approving review), and
standing up a *second*, different credential that pushes straight to `main`
from an always-on local loop would be a new, unreviewed way for this box to
change the site -- exactly the kind of call RULES.md reserves for Sebastian,
not something to wire up quietly inside a single issue's PR.

So this script is a normal tool, run by a normal reviewed change (a builder
pass, or by hand), same as `tools/backfill_basis.py` or any other one-off:

  1. Copies staged rows from BOX_STATE_DIR/published_depth.csv into
     `data/p2p_box_depth.csv` (new file, its own frozen header from today --
     never widens an existing one). Append-only, deduplicated on
     (ts_utc, ccy) so re-running after a partial copy is always safe.
  2. Computes the dated baseline ROADMAP item 12 asks for -- currencies that
     answered, ads per page, success rate, rows per day, bytes per row --
     over whatever window `data/p2p_box_depth.csv` now covers, and writes
     `data/p2p_box_baseline.json`.

The baseline is honest about being incomplete: `complete` is true only once
the covered window reaches 72 hours (BASELINE_TARGET_HOURS). Before that, this
writes the real numbers measured so far and says so -- it never extrapolates
to "about 130,000 ad prices a day" (ROADMAP's own prior ESTIMATE, not this
script's to repeat as fact) before 72 hours of this collector's own
observations exist to say what the real number is. Run with no staged data at
all (nothing deployed yet, or nothing new since the last run), it says so and
changes nothing else.

Usage:
  python3 tools/publish_p2p_box.py              # copy + recompute baseline
  python3 tools/publish_p2p_box.py --dry-run     # print what would move, write nothing
  python3 tools/publish_p2p_box.py --selftest    # offline, tmp dirs only
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import collector_p2p_box as box  # noqa: E402  (needs HERE on sys.path first)

DATA = os.path.join(HERE, "data")
PUBLISHED = os.path.join(DATA, "p2p_box_depth.csv")
BASELINE_OUT = os.path.join(DATA, "p2p_box_baseline.json")
BASELINE_TARGET_HOURS = 72

try:
    import duckdb
except ImportError:
    duckdb = None


# ------------------------------------------------------------- pure core
def dedupe_key(row):
    return (row.get("ts_utc"), row.get("ccy"))


def existing_keys(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as f:
        return {dedupe_key(r) for r in csv.DictReader(f)}


def rows_to_copy(staged_path, published_path):
    """Staged rows not already in the published file, oldest first. Empty,
    never an error, if the staged file does not exist yet -- "nothing
    deployed yet" is a real, nameable state, not a crash."""
    if not os.path.exists(staged_path):
        return []
    seen = existing_keys(published_path)
    out = []
    with open(staged_path, newline="") as f:
        for row in csv.DictReader(f):
            if dedupe_key(row) not in seen:
                out.append(row)
    return out


def copy_rows(rows, published_path):
    if not rows:
        return 0
    new = not os.path.exists(published_path)
    os.makedirs(os.path.dirname(published_path), exist_ok=True)
    with open(published_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=box.PUBLISHED_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def read_published(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _ts(row):
    try:
        t = dt.datetime.fromisoformat(row["ts_utc"])
    except (KeyError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def baseline_from_rows(rows, computed_at):
    """The dated baseline: currencies answered, ads/page, success rate,
    rows/day, bytes/row -- see module docstring. None/empty-safe: a window
    with nothing in it reports nulls and says why, never a fabricated number."""
    if not rows:
        return {
            "computed_at": computed_at, "window_start": None, "window_end": None,
            "hours_covered": 0.0, "complete": False,
            "reason": "no published rows yet -- collector_p2p_box.py has not "
                      "run, or nothing has been copied in with this script yet",
            "currencies_answered": 0, "currencies_asked": 0,
            "ads_per_page_avg": None, "success_rate_pct": None,
            "rows_per_day": None, "bytes_per_row": None,
        }
    stamps = [t for t in (_ts(r) for r in rows) if t is not None]
    start, end = min(stamps), max(stamps)
    hours = max((end - start).total_seconds() / 3600.0, 0.0)

    ok_rows = [r for r in rows if (r.get("source_ok") or "").strip().lower() == "true"]
    ccys = {r["ccy"] for r in rows}
    ccys_ok = {r["ccy"] for r in ok_rows}
    ads_counts = [int(r.get("n_ads_buy") or 0) + int(r.get("n_ads_sell") or 0) for r in ok_rows]

    days = hours / 24.0 if hours > 0 else None
    bytes_total = os.path.getsize(PUBLISHED) if os.path.exists(PUBLISHED) else None
    bytes_per_row = round(bytes_total / len(rows), 1) if bytes_total and rows else None

    return {
        "computed_at": computed_at,
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "hours_covered": round(hours, 2),
        "complete": hours >= BASELINE_TARGET_HOURS,
        "target_hours": BASELINE_TARGET_HOURS,
        "currencies_answered": len(ccys_ok), "currencies_asked": len(ccys),
        "ads_per_page_avg": round(sum(ads_counts) / len(ads_counts), 1) if ads_counts else None,
        "success_rate_pct": round(len(ok_rows) * 100.0 / len(rows), 1),
        "rows_per_day": round(len(rows) / days, 0) if days else None,
        "bytes_per_row": bytes_per_row,
        "n_rows": len(rows),
    }


def raw_parquet_stats(state_dir=box.BOX_STATE_DIR):
    """Row count and on-disk bytes across every raw parquet file this
    collector has written -- None if duckdb is unavailable or nothing has
    been written, never a guess."""
    pattern = os.path.join(box.raw_dir(state_dir), "*", "*.parquet")
    files = glob.glob(pattern)
    if not files or duckdb is None:
        return None
    total_bytes = sum(os.path.getsize(p) for p in files)
    con = duckdb.connect()
    try:
        rows = con.execute(f"SELECT count(*) FROM read_parquet({files!r})").fetchone()[0]
    finally:
        con.close()
    return {"files": len(files), "rows": rows, "bytes": total_bytes,
            "bytes_per_row": round(total_bytes / rows, 1) if rows else None}


# ------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be copied, write nothing")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return

    staged = box.published_stage_path()
    to_copy = rows_to_copy(staged, PUBLISHED)
    print(f"  staged file: {staged} ({'exists' if os.path.exists(staged) else 'missing'})")
    print(f"  new rows to copy into {PUBLISHED}: {len(to_copy)}")

    if a.dry_run:
        print("  --dry-run: nothing written")
        return

    n = copy_rows(to_copy, PUBLISHED)
    print(f"  copied {n} rows -> {PUBLISHED}")

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = baseline_from_rows(read_published(PUBLISHED), now)
    raw_stats = raw_parquet_stats()
    if raw_stats:
        doc["raw_layer"] = raw_stats

    os.makedirs(DATA, exist_ok=True)
    with open(BASELINE_OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"  wrote {BASELINE_OUT}: hours_covered={doc['hours_covered']}, "
          f"complete={doc['complete']}")
    if not doc["complete"]:
        print(f"  [note] baseline is PARTIAL -- {doc['hours_covered']:.1f}h of "
              f"{BASELINE_TARGET_HOURS}h -- re-run this once the box has been "
              f"collecting long enough, do not quote this as the final number")


# -------------------------------------------------------------- selftest
def selftest():
    import tempfile

    # 1. no staged file at all -- a real, nameable state, not an error.
    with tempfile.TemporaryDirectory() as d:
        staged = os.path.join(d, "published_depth.csv")
        published = os.path.join(d, "p2p_box_depth.csv")
        assert rows_to_copy(staged, published) == []
        doc = baseline_from_rows(read_published(published), "2026-10-03T00:00:00+00:00")
        assert doc["complete"] is False and doc["n_rows"] if "n_rows" in doc else True
        assert "no published rows yet" in doc["reason"]
    print("  [ok] no staged data yet -> empty copy, baseline says why, nothing invented")

    # 2. copy is append-only and deduplicated on (ts_utc, ccy) -- re-running
    #    after a partial copy never double-counts a row.
    with tempfile.TemporaryDirectory() as d:
        staged = os.path.join(d, "published_depth.csv")
        published = os.path.join(d, "p2p_box_depth.csv")
        row1 = {f: "" for f in box.PUBLISHED_FIELDS}
        row1.update(ts_utc="2026-10-03T00:00:00+00:00", ccy="VND", source_ok="True",
                    n_ads_buy="10", n_ads_sell="10")
        row2 = dict(row1, ts_utc="2026-10-03T00:10:00+00:00")
        with open(staged, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=box.PUBLISHED_FIELDS)
            w.writeheader()
            w.writerows([row1, row2])
        to_copy = rows_to_copy(staged, published)
        assert len(to_copy) == 2
        assert copy_rows(to_copy, published) == 2
        # Re-run: nothing new to copy, even though the staged file still
        # holds both rows.
        assert rows_to_copy(staged, published) == []
        with open(staged, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=box.PUBLISHED_FIELDS).writerow(
                dict(row1, ts_utc="2026-10-03T00:20:00+00:00"))
        to_copy2 = rows_to_copy(staged, published)
        assert len(to_copy2) == 1 and to_copy2[0]["ts_utc"] == "2026-10-03T00:20:00+00:00"
    print("  [ok] copy is append-only and deduplicated on (ts_utc, ccy); "
          "re-running never double-counts a row already copied")

    # 3. baseline math: hours covered, success rate, ads/page, rows/day.
    rows = []
    base = dt.datetime(2026, 10, 3, 0, 0, tzinfo=dt.timezone.utc)
    for i in range(6):  # six 10-minute rows = 50 minutes covered
        ts = (base + dt.timedelta(minutes=10 * i)).isoformat()
        ok = i != 2  # one failure in the window
        rows.append({"ts_utc": ts, "ccy": "VND", "source_ok": str(ok),
                     "n_ads_buy": "10" if ok else "0", "n_ads_sell": "8" if ok else "0"})
    doc = baseline_from_rows(rows, "2026-10-03T01:00:00+00:00")
    assert doc["hours_covered"] == round(50 / 60, 2), doc
    assert doc["complete"] is False, "well under 72h"
    assert doc["currencies_answered"] == 1 and doc["currencies_asked"] == 1
    assert abs(doc["success_rate_pct"] - (5 / 6 * 100)) < 0.05, doc
    assert doc["ads_per_page_avg"] == 18.0, doc  # (10+8) on each of the 5 ok rows
    print("  [ok] baseline math: hours covered, success rate, ads/page all "
          "computed correctly over a real (short) window")

    # 4. complete flips true only once the window reaches the 72h target.
    long_rows = [{"ts_utc": base.isoformat(), "ccy": "VND", "source_ok": "True",
                  "n_ads_buy": "1", "n_ads_sell": "1"},
                 {"ts_utc": (base + dt.timedelta(hours=72)).isoformat(), "ccy": "VND",
                  "source_ok": "True", "n_ads_buy": "1", "n_ads_sell": "1"}]
    doc_long = baseline_from_rows(long_rows, "2026-10-06T00:00:00+00:00")
    assert doc_long["complete"] is True, doc_long
    print("  [ok] complete=True only once the covered window reaches "
          f"{BASELINE_TARGET_HOURS}h, not before")

    print("\n  ALL SELFTESTS PASSED\n")


if __name__ == "__main__":
    main()
