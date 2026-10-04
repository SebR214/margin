#!/usr/bin/env python3
"""The receipt behind a delivery-time string on sending-money.html (SEB-230):
data/delivery_receipts/<corridor>_<provider>_<day>.json.

sending-money.html already shows a provider's own stated delivery time next
to it (SEB-176, "Wise: arrives in seconds") and already lets a reader click
the cost figure next to it to open a receipt overlay (R2/SEB-186). Clicking
the delivery time itself did nothing. This gives it the same overlay, so a
reader can check a delivery claim the same way they can already check a cost
claim.

Same idea as tools/emit_provider_receipts.py and
tools/emit_pricechange_receipts.py: nothing here is measured or computed.
Every row is read straight out of data/provider_delivery.csv (SEB-176's
sidecar, header `ts_utc,corridor,provider,size_src,delivery_stated,source`,
frozen, never widened). There is no arithmetic to replay -- a provider's
stated delivery time is shown exactly as it was read, so this receipt's own
computation block says that plainly rather than inventing a formula where
there isn't one.

One file per (corridor, provider, day) -- day, not hour, because the exact
hour a reader's page load used is not itself recorded anywhere: Wise's own
estimate can change hour to hour, so a single day can hold several distinct
readings for the same provider, corridor and size. The file carries every
row collected that day so the overlay can show the one that actually matches
what the page is showing, found by the reader's own browser the same way
sending-money.html already picks a row (size then newest timestamp) --
never a day picked for them in advance by this script.

Rebuilt in full every run, same as emit_provider_receipts.py: cheap at
today's row count, and correct even while the current day is still
collecting new hours. A past day's rows in data/provider_delivery.csv never
change, so a past day's receipt comes out byte-identical run to run.

Stdlib only. No wall clock: every value here is read from a row
data/provider_delivery.csv already timestamped. Exits non-zero only if it
cannot write.

Usage: python3 tools/emit_delivery_receipts.py
"""

import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
DELIVERY = os.path.join(DATA, "provider_delivery.csv")
OUT_DIR = os.path.join(DATA, "delivery_receipts")


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def safe_key_part(s):
    """Mirrors emit_pricechange_receipts.py's own safe_key_part -- a
    provider name made safe for a filename."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")
    return s or "unknown"


def corridor_slug(corridor):
    return (corridor or "").replace("->", "-")


def build():
    groups = {}
    for r in rows(DELIVERY):
        corridor = (r.get("corridor") or "").strip()
        provider = (r.get("provider") or "").strip()
        ts_utc = (r.get("ts_utc") or "").strip()
        stated = (r.get("delivery_stated") or "").strip()
        size = num(r.get("size_src"))
        if not corridor or not provider or not ts_utc or not stated or size is None:
            continue
        day = ts_utc[:10]
        key = (corridor, provider, day)
        groups.setdefault(key, []).append({
            "ts_utc": ts_utc,
            "size_src": int(size),
            "delivery_stated": stated,
            "source": r.get("source"),
        })

    out = {}
    for (corridor, provider, day), entries in groups.items():
        entries.sort(key=lambda e: (e["ts_utc"], e["size_src"]))
        filename = f"{corridor_slug(corridor)}_{safe_key_part(provider)}_{day}"
        out[filename] = {
            "corridor": corridor,
            "provider": provider,
            "day": day,
            "rows": entries,
            "computation": {
                "formula": None,
                "meaning": f"stated by {provider}, read directly, not calculated.",
                "note": "delivery_stated is copied verbatim from the matching row in "
                        "data/provider_delivery.csv -- never computed.",
            },
            "source_files": ["data/provider_delivery.csv"],
        }
    return out


def main():
    receipts = build()
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        for filename, receipt in receipts.items():
            with open(os.path.join(OUT_DIR, f"{filename}.json"), "w") as f:
                json.dump(receipt, f, indent=2, sort_keys=True)
                f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write delivery receipts: {e}", file=sys.stderr)
        sys.exit(1)

    n_rows = sum(len(r["rows"]) for r in receipts.values())
    print(f"  wrote {len(receipts)} delivery receipts -> data/delivery_receipts/ "
          f"({n_rows} delivery rows across every corridor/provider/day on file)")


if __name__ == "__main__":
    main()
