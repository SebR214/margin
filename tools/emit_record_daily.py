#!/usr/bin/env python3
"""data/record_daily.json: the record, one row per day since the first reading.

Schema
    {
      "as_of_utc":  newest stored reading timestamp (no wall clock),
      "first_day":  "2026-08-10",
      "last_day":   day of as_of_utc,
      "definition": what counts, in words (see tools/record_common.py),
      "files":      {file: readings counted}   the files that count, and how many each,
      "days": [
        {"day": "YYYY-MM-DD",
         "readings":            readings stored that day,
         "readings_cumulative": readings stored from the first reading to the end of that day,
         "sources_live":        distinct sources with at least one reading that day,
         "sources_cumulative":  distinct sources seen so far,
         "currencies":          distinct currencies with a reading that day,
         "currencies_cumulative": ... seen so far,
         "routes_priced":       distinct routes with a reading that day,
         "routes_cumulative":   ... seen so far,
         "hours_collected":     distinct UTC hours that day with any reading,
         "hours_cumulative":    distinct hours so far}
        ...one row for every calendar day, none skipped...
      ],
      "totals": {"readings", "sources", "currencies", "routes", "hours_collected"}  latest values
    }
Every figure a page counts up is a per-day series, so a replay at any date from
2026-08-10 shows that day's value. Reads stored files only; idempotent; stdlib only.

Usage: python3 tools/emit_record_daily.py [--self-test]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_common as rc  # noqa: E402

OUT = os.path.join(rc.DATA, "record_daily.json")

DEFINITION = (
    "A reading is one stored row in basis.csv, p2p_basis.csv, p2p_okx.csv, fx_rates.csv, "
    "provider_quotes.csv, providers.csv, providers_audphp.csv, providers_nzdphp.csv, "
    "providers_sgdinr.csv, providers_usdinr.csv, providers_usdmxn.csv, providers_usdngn.csv, "
    "samples.csv, corridor_variants.csv or stable_spread.csv, dated 2026-08-10 or later, whose "
    "source_ok is not False (fx_rates.csv has no such column: every row counts). Failed attempts "
    "are not readings. Files derived from these (depth, waterfalls, signals, price changes) are "
    "not counted. A source is a venue, exchange, aggregator, exchange-rate feed or provider named "
    "in those rows. Currencies are the ccy column of basis, p2p_basis, p2p_okx, fx_rates and "
    "stable_spread. Routes are the corridors in provider_quotes, providers*, samples and "
    "corridor_variants. Hours are distinct UTC hours with at least one reading."
)


def build():
    rows = [r for r in rc.readings() if r["ok"]]
    if not rows:
        raise SystemExit("no readings stored")
    as_of = rows[-1]["ts"]
    first_day, last_day = rc.START_DAY, rc.day_of(as_of)
    by_day = {}
    files = {}
    for r in rows:
        d = by_day.setdefault(rc.day_of(r["ts"]), dict(n=0, src=set(), ccy=set(), rte=set(), hrs=set()))
        d["n"] += 1
        d["hrs"].add(rc.hour_of(r["ts"]))
        d["src"].update(s for s, _ in r["sources"])
        if r["ccy"]:
            d["ccy"].add(r["ccy"])
        if r["route"]:
            d["rte"].add(r["route"])
        files[r["file"]] = files.get(r["file"], 0) + 1
    days, cum, src_c, ccy_c, rte_c, hr_c = [], 0, set(), set(), set(), set()
    for day in rc.day_range(first_day, last_day):
        d = by_day.get(day, dict(n=0, src=set(), ccy=set(), rte=set(), hrs=set()))
        cum += d["n"]
        src_c |= d["src"]
        ccy_c |= d["ccy"]
        rte_c |= d["rte"]
        hr_c |= d["hrs"]
        days.append({
            "day": day, "readings": d["n"], "readings_cumulative": cum,
            "sources_live": len(d["src"]), "sources_cumulative": len(src_c),
            "currencies": len(d["ccy"]), "currencies_cumulative": len(ccy_c),
            "routes_priced": len(d["rte"]), "routes_cumulative": len(rte_c),
            "hours_collected": len(d["hrs"]), "hours_cumulative": len(hr_c),
        })
    return {
        "as_of_utc": rc.iso_z(as_of), "first_day": first_day, "last_day": last_day,
        "definition": DEFINITION, "files": {k: files[k] for k in sorted(files)},
        "days": days,
        "totals": {"readings": cum, "sources": len(src_c), "currencies": len(ccy_c),
                   "routes": len(rte_c), "hours_collected": len(hr_c)},
    }


def self_test(doc):
    rc.assert_no_nan(doc)
    days = doc["days"]
    assert days[0]["day"] == rc.START_DAY, "first day"
    assert [d["day"] for d in days] == rc.day_range(doc["first_day"], doc["last_day"]), "every day present"
    for k in ("readings_cumulative", "sources_cumulative", "currencies_cumulative",
              "routes_cumulative", "hours_cumulative"):
        v = [d[k] for d in days]
        assert all(b >= a for a, b in zip(v, v[1:])), k + " must not decrease"
    assert all(d["readings"] >= 0 for d in days)
    assert days[-1]["readings_cumulative"] == doc["totals"]["readings"] == sum(doc["files"].values())
    assert sum(d["readings"] for d in days) == doc["totals"]["readings"]
    assert days[-1]["hours_cumulative"] == doc["totals"]["hours_collected"]
    assert doc["totals"]["currencies"] <= 60, "more currencies than the index tracks"
    print("record_daily self-test ok: %d days, %d readings" % (len(days), doc["totals"]["readings"]))


def main():
    doc = build()
    if "--self-test" in sys.argv:
        self_test(doc)
        return
    self_test(doc)
    rc.write_json(OUT, doc)
    t = doc["totals"]
    print("record_daily: %d days, %d readings, %d sources, %d currencies, %d routes, %d hours" % (
        len(doc["days"]), t["readings"], t["sources"], t["currencies"], t["routes"], t["hours_collected"]))


if __name__ == "__main__":
    main()
