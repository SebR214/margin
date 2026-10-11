#!/usr/bin/env python3
"""A new source cannot feed the index on arrival (SEB-302).

Every source that can feed a published price (an exchange order book, a broker,
the Binance board, the OKX board) must be listed as `approved` in
data/source_registry.json. A source that is not listed, or is listed as
`quarantine`, still gets its rows collected into its own place, but
tools/emit_countries.py ignores it: it cannot move a published number.

A source leaves quarantine only by passing `evaluate()`:
  - at least QUARANTINE_DAYS distinct days of its own rows, and
  - at least MIN_SHARED_HOURS hours in which an approved source priced the same
    market, and
  - a median gap to those approved sources of no more than MAX_MEDIAN_GAP_PCT.
A source with no approved neighbour in its market has nothing to be compared
with, so it stays in quarantine. Then a person, or a spec Seb approved, changes
its status in the registry in a PR.

Sources already in use on 2026-10-11 are listed as approved with the reason
'in use before the 7-day rule'; nothing that was feeding a number stops.

    python3 tools/source_gate.py --init        # (re)build the registry from the stored rows, once
    python3 tools/source_gate.py --status      # who is approved, who is in quarantine, and who is unlisted
    python3 tools/source_gate.py --evaluate NAME
    python3 tools/source_gate.py --self-test
"""
import collections
import csv
import datetime as dt
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REGISTRY = os.path.join(DATA, "source_registry.json")
QUARANTINE_DAYS = 7
MIN_SHARED_HOURS = 100
MAX_MEDIAN_GAP_PCT = 3.0


def load_registry(path=REGISTRY):
    if not os.path.exists(path):
        return {"sources": {}}
    with open(path) as f:
        return json.load(f)


def approved(name, registry=None):
    """True only for a source listed as approved. Unlisted means not approved."""
    reg = registry if registry is not None else load_registry()
    return (reg.get("sources", {}).get(name) or {}).get("status") == "approved"


def _read(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def evaluate(own, neighbours):
    """own: {ccy: {hour: price}} for the candidate; neighbours: {ccy: {hour: median price of approved sources}}.
    Returns (ok, reasons, facts). Pure, so the test can feed it every case."""
    days = {h[:10] for series in own.values() for h in series}
    gaps, shared = [], 0
    for ccy, series in own.items():
        ref = neighbours.get(ccy, {})
        for h, p in series.items():
            if h in ref and ref[h]:
                gaps.append(abs(p / ref[h] - 1) * 100)
                shared += 1
    reasons = []
    if len(days) < QUARANTINE_DAYS:
        reasons.append("%d day(s) of its own rows, %d needed" % (len(days), QUARANTINE_DAYS))
    if shared < MIN_SHARED_HOURS:
        reasons.append("%d shared hour(s) with an approved source, %d needed" % (shared, MIN_SHARED_HOURS))
    med = round(statistics.median(gaps), 2) if gaps else None
    if med is not None and med > MAX_MEDIAN_GAP_PCT:
        reasons.append("median gap to approved sources is %.2f%%, over %.1f%%" % (med, MAX_MEDIAN_GAP_PCT))
    return not reasons, reasons, {"days": len(days), "shared_hours": shared, "median_gap_pct": med}


def venue_prices():
    """{venue or board: {ccy: {hour: buy price}}} from real rows only."""
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in _read("basis.csv"):
        v = r.get("venue") or ""
        if r.get("source_ok") != "True" or (v.startswith("CriptoYa (") and v.endswith(")")):
            continue
        try:
            p = float(r.get("usdt_ask") or r.get("usdt_mid") or 0)
        except ValueError:
            continue
        if p > 0:
            out[v][r["ccy"]][r["ts_utc"][:13]] = p
    for name, fn in (("binance_p2p", "p2p_basis.csv"), ("okx_p2p", "p2p_okx.csv")):
        for r in _read(fn):
            try:
                p = float(r.get("buy_median") or 0)
            except ValueError:
                continue
            if r.get("source_ok") == "True" and p > 0:
                out[name][r["ccy"]][r["ts_utc"][:13]] = p
    return out


def neighbours_for(name, prices, registry):
    """For each market the candidate prices, the median of the approved sources' price in each hour."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for other, by_ccy in prices.items():
        if other == name or not approved(other, registry):
            continue
        for ccy, series in by_ccy.items():
            for h, p in series.items():
                per[ccy][h].append(p)
    return {ccy: {h: statistics.median(v) for h, v in hs.items()} for ccy, hs in per.items()}


def init():
    prices = venue_prices()
    first = {}
    for name, by_ccy in prices.items():
        first[name] = min(h for series in by_ccy.values() for h in series)[:10]
    reg = {"quarantine_days": QUARANTINE_DAYS, "min_shared_hours": MIN_SHARED_HOURS, "max_median_gap_pct": MAX_MEDIAN_GAP_PCT,
           "sources": {n: {"status": "approved", "first_row": first[n], "basis": "in use before the 7-day rule (2026-10-11)"}
                       for n in sorted(first)}}
    with open(REGISTRY, "w") as f:
        json.dump(reg, f, indent=1, sort_keys=True)
        f.write("\n")
    return reg


def status():
    reg, prices = load_registry(), venue_prices()
    unlisted = sorted(n for n in prices if n not in reg["sources"])
    quarantined = sorted(n for n, s in reg["sources"].items() if s.get("status") != "approved")
    return {"approved": sorted(n for n in reg["sources"] if approved(n, reg)), "quarantine": quarantined, "unlisted_with_rows": unlisted}


def self_test():
    hours = ["2026-10-%02dT%02d" % (1 + i // 24, i % 24) for i in range(9 * 24)]
    ref = {"PHP": {h: 100.0 for h in hours}}
    good = {"PHP": {h: 100.8 for h in hours}}
    ok, why, facts = evaluate(good, ref)
    assert ok and facts["days"] == 9 and facts["median_gap_pct"] == 0.8, (why, facts)
    # too young: 3 days of rows
    ok, why, _ = evaluate({"PHP": {h: 100.0 for h in hours[:72]}}, ref)
    assert not ok and any("day(s)" in w for w in why), why
    # old enough but 12% from the approved sources: an invented market
    ok, why, _ = evaluate({"PHP": {h: 112.0 for h in hours}}, ref)
    assert not ok and any("median gap" in w for w in why), why
    # nothing to compare with: stays in quarantine
    ok, why, _ = evaluate({"XYZ": {h: 5.0 for h in hours}}, ref)
    assert not ok and any("shared hour" in w for w in why), why
    # the registry: unlisted and quarantined sources are not approved
    reg = {"sources": {"A": {"status": "approved"}, "B": {"status": "quarantine"}}}
    assert approved("A", reg) and not approved("B", reg) and not approved("C", reg)
    assert approved("A", {"sources": {}}) is False
    print("source_gate self-test: ok")


def main():
    a = sys.argv[1:]
    if "--self-test" in a:
        return self_test() or 0
    if "--init" in a:
        reg = init()
        print("wrote data/source_registry.json: %d sources approved" % len(reg["sources"]))
        return 0
    if "--status" in a:
        s = status()
        print(json.dumps(s, indent=1))
        return 1 if s["unlisted_with_rows"] else 0
    if "--evaluate" in a:
        name = a[a.index("--evaluate") + 1]
        prices, reg = venue_prices(), load_registry()
        ok, why, facts = evaluate(prices.get(name, {}), neighbours_for(name, prices, reg))
        print(json.dumps({"source": name, "may_leave_quarantine": ok, "reasons": why, **facts}, indent=1))
        return 0 if ok else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
