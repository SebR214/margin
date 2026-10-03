#!/usr/bin/env python3
"""The receipt behind a provider's ranked cost on sending-money.html (SEB-186):
data/provider_receipts/<corridor>_<size>_<hour>.json.

Same idea as tools/emit_receipts.py (SEB-56/R2 for index/country numbers) and
tools/emit_corridor_receipts.py (SEB-178, for corridor.html's cost figures):
nothing here is measured fresh. This re-opens data/providers_latest.json
(built by tools/emit_providers.py) plus whichever raw CSV each row's own
`source` field names, and shows that row next to the number it produced, so
js/receipt_replay.js's overlay can replay a provider's cost the same way it
already replays an index number and a corridor's.

Everything comes from data already on disk:
  data/providers_latest.json  the computed ranking, one row per provider per
                               corridor per size -- source ("own", "comparison",
                               "measured" or "missing"), cost_pct, rate, fee,
                               also_quoted_pct. Must run after
                               tools/emit_providers.py.
  data/provider_quotes.csv    a provider's own published quote, where
                               source == "own" (collector_providers.py).
  data/providers.csv and its per-corridor siblings (providers_usdmxn.csv,
                               providers_audphp.csv, providers_nzdphp.csv,
                               providers_usdngn.csv, providers_usdinr.csv,
                               providers_sgdinr.csv) -- the public comparison
                               panel, where source == "comparison".
  data/samples.csv            the stablecoin route's own measured cost, where
                               source == "measured".

One file per (corridor, size), at the hour providers_latest.json's own
panel_hour_utc names for that corridor (falling back to crypto_hour_utc,
same fallback sending-money.html's own meta line already uses) -- not a
per-provider hour, since a reader picks a corridor and a size, not a
provider, before anything is shown. A new hour's snapshot makes a new file;
the previous hour's file is left alone, since its own filename already
carries that hour.

THE WIRING DECISION, found while building this (see the issue): sending-
money.html's own render step does not simply show each row's stored
cost_pct. An "own"-sourced row with a comparison figure also on file
(`also_quoted_pct`) is displayed using THAT comparison number instead --
the page's own comment says why: "A provider that only has a direct quote
is shown as 'not checked yet'... direct quotes aren't verified [against an
independent source]". A bare "own" row with no comparison fallback is not
shown as a number at all ("direct quote, not checked yet").

So only two shapes of row ever show a real, clickable cost figure on that
page: a "comparison" row, and an "own" row that has a comparison fallback
(displayed AS the comparison figure). This receipt still carries an honest,
complete entry for every row providers_latest.json has -- own, comparison,
measured, missing alike, the same exhaustive-regardless-of-published rule
emit_receipts.py follows -- but js/receipt_replay.js and sending-money.html
only wire a click handler to the ones whose receipt computation cannot
disagree with the number the reader is looking at: "comparison" rows
outright, plus "own" rows via their own also_quoted_pct note. An "own" row
with no fallback, or a "missing" row, carries a receipt here (so the data is
never silently incomplete) but is not clickable from the page, matching
what is already true today: neither shows a real number to click.

The stablecoin ("measured") row already has its own full step-by-step
receipt via corridor.html (SEB-178) -- this file still carries a plain entry
for it, for completeness, but sending-money.html does not wire a second
click handler to it; its existing "every cost, step by step" link is
untouched.

Stdlib only. No wall clock: every value here is read from a row
providers_latest.json or a collector already timestamped. Exits non-zero
only if it cannot write.

Usage: python3 tools/emit_provider_receipts.py
"""

import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
PROVIDERS_LATEST = os.path.join(DATA, "providers_latest.json")
QUOTES = os.path.join(DATA, "provider_quotes.csv")
SAMPLES = os.path.join(DATA, "samples.csv")
OUT_DIR = os.path.join(DATA, "provider_receipts")

# Mirrors tools/emit_providers.py's own PANELS -- each corridor's comparison
# panel lives in its own file, since providers.csv has no corridor column
# and a frozen schema.
PANELS = {
    "SGD->PHP": "providers.csv",
    "USD->MXN": "providers_usdmxn.csv",
    "AUD->PHP": "providers_audphp.csv",
    "NZD->PHP": "providers_nzdphp.csv",
    "USD->NGN": "providers_usdngn.csv",
    "USD->INR": "providers_usdinr.csv",
    "SGD->INR": "providers_sgdinr.csv",
}

FORMULA = ("(1 minus the amount received divided by (the amount sent times the "
           "mid-market exchange rate at the time)), times 100")


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(row, key):
    if row is None:
        return None
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def flag(row, key):
    return (row.get(key) or "").strip().lower() == "true"


def parse_ts(s):
    try:
        t = dt.datetime.fromisoformat((s or "").strip())
    except ValueError:
        return None
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t


def newest_hour(rs, field):
    stamps = [t for t in (parse_ts(r.get(field)) for r in rs) if t]
    if not stamps:
        return None
    return max(stamps).replace(minute=0, second=0, microsecond=0)


def in_hour(rs, hour, field):
    out = []
    for r in rs:
        t = parse_ts(r.get(field))
        if t and t.replace(minute=0, second=0, microsecond=0) == hour:
            out.append(r)
    return out


def hour_slug(ts_iso):
    return (ts_iso or "")[:13]


def corridor_slug(corridor):
    return corridor.replace("->", "-")


# ------------------------------------------------------------ row finders
def own_quote_row(corridor, size, provider):
    """The exact data/provider_quotes.csv row an "own" entry came from --
    same hour selection as emit_providers.py's own_quotes() (the newest
    source_ok hour across the WHOLE file, not just this corridor), so a row
    is found here exactly when providers_latest.json actually used one."""
    ok = [r for r in rows(QUOTES) if flag(r, "source_ok")]
    hour = newest_hour(ok, "ts_utc")
    if hour is None:
        return None
    for r in in_hour(ok, hour, "ts_utc"):
        if (r.get("corridor") == corridor and num(r, "size_src") == size
                and r.get("provider") == provider):
            return r
    return None


def panel_quote_row(corridor, size, provider):
    """The exact comparison-panel CSV row a "comparison" entry came from --
    same per-corridor newest-hour selection as emit_providers.py's own
    panel_quotes()."""
    panel_file = PANELS.get(corridor)
    if not panel_file:
        return None
    ok = [r for r in rows(os.path.join(DATA, panel_file))
          if flag(r, "source_ok") and r.get("provider")]
    hour = newest_hour(ok, "ts_utc")
    if hour is None:
        return None
    for r in in_hour(ok, hour, "ts_utc"):
        if num(r, "notional_src") == size and r.get("provider") == provider:
            return r
    return None


def samples_row(corridor, size):
    """The data/samples.csv row a "measured" entry came from -- same
    per-corridor newest-hour selection as emit_providers.py's own
    crypto_route()."""
    ok = [r for r in rows(SAMPLES)
          if (r.get("corridor") or "").strip() == corridor and flag(r, "source_ok")]
    hour = newest_hour(ok, "ts")
    if hour is None:
        return None
    for r in in_hour(ok, hour, "ts"):
        if num(r, "notional_src") == size:
            return r
    return None


# ----------------------------------------------------------- row builders
def stale_entry(reason):
    """providers_latest.json names a source this script can no longer find
    the exact row for -- the file has moved on to a newer hour since
    providers_latest.json was last built. Said plainly rather than guessed
    at with a stand-in row."""
    return {
        "evidence": {"status": "stale", "meaning": reason},
        "computation": None,
        "source_files": [],
    }


def own_quote_evidence(src_row, provider):
    if src_row is None:
        return None
    rate, fee, received = num(src_row, "rate"), num(src_row, "fee_src"), num(src_row, "received_dst")
    return {
        "provider_site": src_row.get("source"),
        "rate": rate,
        "fee": fee,
        "received": received,
        "collected_at": src_row.get("ts_utc"),
        "meaning": f"{provider}'s own published quote: at a rate of {rate}, with a stated fee of {fee}, "
                   f"sending this amount lands {received}.",
    }


def own_entry(corridor, size, row_out):
    """A provider's own-published-quote row. Two different shapes, because
    sending-money.html itself shows two different numbers depending on
    whether a comparison figure also exists for this provider/size/hour
    (see this file's own docstring, "THE WIRING DECISION"):

    - also_quoted_pct present: the PAGE shows the comparison figure, not
      this provider's own number, so this receipt's headline evidence and
      computation describe the comparison figure too -- the provider's own
      quote is still shown, as supporting context underneath, never as the
      number the math step claims to explain. Getting this backwards is
      exactly the overlay-disagrees-with-the-page bug class SEB-173 was
      built to catch.
    - no also_quoted_pct: the page shows no number at all for this row
      ("direct quote, not checked yet"), so this receipt is free to
      describe the provider's own number as the headline -- nothing on the
      page could ever disagree with it, because nothing on the page shows
      it as a ranked figure.
    """
    provider = row_out.get("provider")
    src_row = own_quote_row(corridor, size, provider)
    own_evidence = own_quote_evidence(src_row, provider)
    also = row_out.get("also_quoted_pct")

    if also is not None:
        panel_row = panel_quote_row(corridor, size, provider)
        panel_file = PANELS.get(corridor)
        if panel_row is None or panel_file is None:
            return stale_entry(
                f"data/{panel_file or '?'} has moved on to a newer hour since providers_latest.json "
                "was last rebuilt -- the exact row behind this figure cannot be shown right now."
            )
        landed = num(panel_row, "landed_dst")
        evidence = {
            "status": "comparison",
            "landed": landed,
            "collected_at": panel_row.get("ts_utc"),
            "meaning": f"A public price comparison service quotes {provider}: this amount lands {landed} "
                       "after every fee.",
            "own_quote": own_evidence,
            "own_quote_note": (
                f"{provider} also publishes its own quote directly, shown above, at a different rate and "
                "fee. This page shows the public comparison figure here instead, so every provider is "
                "checked the same independent way." if own_evidence else None
            ),
        }
        computation = {
            "formula": FORMULA,
            "result_pct": also,
            "meaning": "The share of the amount sent the comparison service's quote costs -- matches "
                       "providers_latest.json's own stored also_quoted_pct for this row, which is the "
                       "figure sending-money.html actually shows for this provider.",
            "note": None,
        }
        source_files = sorted({"data/" + panel_file} | ({"data/provider_quotes.csv"} if own_evidence else set()))
        return {"evidence": evidence, "computation": computation, "source_files": source_files}

    if own_evidence is None:
        return stale_entry(
            "data/provider_quotes.csv has moved on to a newer hour since providers_latest.json "
            "was last rebuilt -- the exact row behind this figure cannot be shown right now."
        )
    evidence = dict(own_evidence, status="own")
    computation = {
        "formula": FORMULA,
        "result_pct": row_out.get("cost_pct"),
        "meaning": "The share of the amount sent this quote's rate and fee, together, cost -- matches "
                   "providers_latest.json's own stored figure for this row.",
        "note": f"This is {provider}'s own published number. It is not checked against an independent "
                "comparison service, so sending-money.html does not show it as a ranked figure yet.",
    }
    return {"evidence": evidence, "computation": computation, "source_files": ["data/provider_quotes.csv"]}


def comparison_entry(corridor, size, row_out):
    provider = row_out.get("provider")
    src_row = panel_quote_row(corridor, size, provider)
    panel_file = PANELS.get(corridor)
    if src_row is None or panel_file is None:
        return stale_entry(
            f"data/{panel_file or '?'} has moved on to a newer hour since providers_latest.json "
            "was last rebuilt -- the exact row behind this figure cannot be shown right now."
        )
    landed = num(src_row, "landed_dst")
    evidence = {
        "status": "comparison",
        "landed": landed,
        "collected_at": src_row.get("ts_utc"),
        "meaning": f"A public price comparison service quotes {provider}: this amount lands {landed} after "
                   "every fee.",
    }
    computation = {
        "formula": FORMULA,
        "result_pct": row_out.get("cost_pct"),
        "meaning": "Matches providers_latest.json's own stored figure for this row.",
        "note": None,
    }
    return {"evidence": evidence, "computation": computation, "source_files": ["data/" + panel_file]}


def measured_entry(corridor, size, row_out):
    src_row = samples_row(corridor, size)
    if src_row is None:
        return stale_entry(
            "data/samples.csv has moved on to a newer hour since providers_latest.json was last "
            "rebuilt -- the exact row behind this figure cannot be shown right now."
        )
    files = ["data/samples.csv"]
    venues = row_out.get("venues")
    evidence = {
        "status": "measured",
        "collected_at": src_row.get("ts"),
        "meaning": "Priced on real exchanges this hour, every fee included.",
        "venues_summary": (f"Cheapest of {len(venues['combos'])} exchange pairs this hour."
                            if venues and venues.get("combos") else None),
    }
    if venues:
        files.append("data/stable_venues.csv")
    computation = {
        "formula": None,
        "result_pct": row_out.get("cost_pct"),
        "meaning": "Matches providers_latest.json's own stored figure for this row.",
        "note": "This route has its own full step-by-step receipt -- see the link next to it on the page.",
    }
    return {"evidence": evidence, "computation": computation, "source_files": files}


def missing_entry(corridor, size, row_out):
    provider = row_out.get("provider")
    return {
        "evidence": {
            "status": "missing",
            "meaning": f"{provider} has quoted this corridor in the recent past but not this particular "
                       "hour -- no price to show.",
        },
        "computation": None,
        "source_files": [],
    }


BUILDERS = {"own": own_entry, "comparison": comparison_entry, "measured": measured_entry}


def build_row(corridor, size, row_out):
    builder = BUILDERS.get(row_out.get("source"), missing_entry)
    built = builder(corridor, size, row_out)
    return {
        "provider": row_out.get("provider"),
        "source": row_out.get("source"),
        "rank": row_out.get("rank"),
        "cost_pct": row_out.get("cost_pct"),
        "costs": row_out.get("costs"),
        "evidence": built["evidence"],
        "computation": built["computation"],
        "source_files": built["source_files"],
    }


def build():
    if not os.path.exists(PROVIDERS_LATEST):
        return {}
    with open(PROVIDERS_LATEST) as f:
        snap = json.load(f)

    out = {}
    for corridor, route in sorted(snap.get("corridors", {}).items()):
        hour_iso = route.get("panel_hour_utc") or route.get("crypto_hour_utc")
        if not hour_iso:
            continue  # nothing sampled for this corridor yet -- no file to write
        hour = hour_slug(hour_iso)
        for size_key, size_doc in route.get("sizes", {}).items():
            size = size_doc.get("amount")
            if size is None:
                continue
            entries = [build_row(corridor, size, r) for r in size_doc.get("rows", [])]
            source_files = sorted(
                {f for e in entries for f in e["source_files"]} | {"data/providers_latest.json"}
            )
            filename = f"{corridor_slug(corridor)}_{size}_{hour}"
            out[filename] = {
                "corridor": corridor,
                "size": size,
                "size_words": size_doc.get("amount_words"),
                "hour_utc": hour,
                "panel_hour_utc": route.get("panel_hour_utc"),
                "crypto_hour_utc": route.get("crypto_hour_utc"),
                "rows": entries,
                "source_files": source_files,
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
        print(f"  [error] cannot write provider receipts: {e}", file=sys.stderr)
        sys.exit(1)

    n_rows = sum(len(r["rows"]) for r in receipts.values())
    n_clickable = sum(
        1 for r in receipts.values() for row in r["rows"]
        if row["computation"] and row["evidence"].get("status") == "comparison"
    )
    print(f"  wrote {len(receipts)} provider receipts -> data/provider_receipts/ "
          f"({n_rows} provider rows, {n_clickable} with a clickable comparison figure)")


if __name__ == "__main__":
    main()
