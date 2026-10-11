#!/usr/bin/env python3
"""Every pair of sources measuring the same market, compared hour by hour (SEB-302).

A source cannot check itself. For each country this reads every source that has
priced it in the last WINDOW_DAYS (an exchange order book, a broker quote, the
Binance board, the OKX board), lines them up on the same UTC hour, and for each
pair records how far apart their buy prices were. Two things come out:

  one_source   True when the price on the site rests on one source only. The
               site marks those markets "One source" (copy.json, countries.oneSource).
  pairs        per pair: hours compared, median gap, share of hours over
               GAP_PCT, and `flag`: the most recent run of hours over GAP_PCT has
               lasted LASTS_HOURS or more. Only sources of the same kind (order
               book, broker, person-to-person board) are flagged; a broker and
               a board differ by design. A flag is a possible finding, not a
               conclusion.

Only prices that are real are compared: a row with source_ok=false (including a
row tools/../board_guard.py refused) is not a price. Prices are each source's
buy side, local money per dollar. Stored rows only; nothing is filled in.

Writes data/source_pairs.json. No model, no network, stdlib only.

    python3 tools/emit_source_pairs.py
    python3 tools/emit_source_pairs.py --self-test
"""
import collections
import csv
import datetime as dt
import glob
import itertools
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "source_pairs.json")
WINDOW_DAYS = 30
GAP_PCT = 2.0            # two sources this far apart (percent of the lower) count as disagreeing
LASTS_HOURS = 24         # a gap must last this many hours in a row, up to now, to be flagged
MIN_COMMON_HOURS = 24    # fewer shared hours than this is not enough to compare


def hour_of(ts):
    return ts[:13]


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def read(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def prices_by_source(basis_rows, binance_rows, okx_rows, since_hour):
    """{ccy: {source: {hour: buy price}}} from real rows only, newest row of an hour wins."""
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in basis_rows:
        venue = r.get("venue") or ""
        if r.get("source_ok") != "True" or (venue.startswith("CriptoYa (") and venue.endswith(")")):
            continue
        p = num(r.get("usdt_ask")) or num(r.get("usdt_mid"))
        h = hour_of(r["ts_utc"])
        if p and h >= since_hour:
            out[r["ccy"]][venue][h] = p
    for name, rows in (("binance_p2p", binance_rows), ("okx_p2p", okx_rows)):
        for r in rows:
            p = num(r.get("buy_median"))
            h = hour_of(r["ts_utc"])
            if r.get("source_ok") == "True" and p and h >= since_hour:
                out[r["ccy"]][name][h] = p
    return out


def kind_of(source):
    """What sort of source this is. Only sources of one kind are comparable: a broker's quote,
    an exchange's order book and a person-to-person board differ by design, not by error."""
    if source in ("binance_p2p", "okx_p2p"):
        return "person_to_person"
    return "broker" if source.startswith("CriptoYa:") else "order_book"


def compare(a, b):
    """Hour-by-hour comparison of two {hour: price} series, or None if they barely overlap."""
    common = sorted(set(a) & set(b))
    if len(common) < MIN_COMMON_HOURS:
        return None
    gaps = [(abs(a[h] - b[h]) / min(a[h], b[h]) * 100.0, h) for h in common]
    run = 0
    for g, _ in reversed(gaps):
        if g > GAP_PCT:
            run += 1
        else:
            break
    over = sum(1 for g, _ in gaps if g > GAP_PCT)
    return {"hours": len(common), "median_gap_pct": round(statistics.median(g for g, _ in gaps), 2),
            "share_over_gap": round(over / len(common), 3), "last_gap_pct": round(gaps[-1][0], 2),
            "last_hour": gaps[-1][1], "hours_over_gap_in_a_row": run, "flag": run >= LASTS_HOURS}


def build(series, feeding, as_of):
    """series: {ccy: {source: {hour: price}}}; feeding: {ccy: [sources behind the published price]}."""
    markets = {}
    for ccy in sorted(set(series) | set(feeding)):
        pairs = []
        for (na, sa), (nb, sb) in itertools.combinations(sorted(series.get(ccy, {}).items()), 2):
            c = compare(sa, sb)
            if c:
                same = kind_of(na) == kind_of(nb)
                c["flag"] = c["flag"] and same           # unlike kinds differ by design: compared, never flagged
                pairs.append({"a": na, "b": nb, "same_kind": same, "kind": kind_of(na) if same else "mixed", **c})
        markets[ccy] = {"sources_behind_price": feeding.get(ccy, []),
                        "one_source": len(feeding.get(ccy, [])) == 1,
                        "sources_seen": sorted(series.get(ccy, {})), "pairs": pairs}
    return {"as_of_utc": as_of, "window_days": WINDOW_DAYS, "gap_pct": GAP_PCT, "lasts_hours": LASTS_HOURS,
            "min_common_hours": MIN_COMMON_HOURS, "markets": markets}


def feeding_from_countries():
    out = {}
    for f in glob.glob(os.path.join(DATA, "countries", "*.json")):
        if " " in os.path.basename(f):
            continue
        d = json.load(open(f))
        if d.get("source_class") is None or d.get("index_pct") is None:
            continue                      # no price this hour: nothing rests on any source
        v = [x.get("venue") for x in d.get("venues") or [] if x.get("venue")]
        out[d["ccy"]] = v or ["unknown"]
    return out


def self_test():
    hours = ["2026-10-%02dT%02d" % (1 + i // 24, i % 24) for i in range(60)]
    flat = {h: 100.0 for h in hours}
    # a second source 5% above for the last 30 hours only
    late = {h: (105.0 if i >= 30 else 100.5) for i, h in enumerate(hours)}
    brief = {h: (105.0 if i >= 50 else 100.5) for i, h in enumerate(hours)}
    c = compare(flat, late)
    assert c["flag"] and c["hours_over_gap_in_a_row"] == 30 and c["hours"] == 60, c
    b = compare(flat, brief)
    assert not b["flag"] and b["hours_over_gap_in_a_row"] == 10, b
    assert compare(flat, {h: 100.0 for h in hours[:10]}) is None, "too little overlap is not a comparison"
    # real rows only: a refused row (source_ok False) is not a price, the venue aggregate is not a source
    basis = [{"ts_utc": h + ":05:00", "venue": "BTCTurk", "ccy": "TRY", "usdt_ask": "49.0", "usdt_mid": "", "source_ok": "True"} for h in hours]
    basis.append({"ts_utc": hours[-1] + ":06:00", "venue": "CriptoYa (ARS)", "ccy": "ARS", "usdt_ask": "1", "usdt_mid": "", "source_ok": "True"})
    binance = [{"ts_utc": h + ":06:00", "ccy": "TRY", "buy_median": "51.0", "source_ok": "True"} for h in hours]
    binance.append({"ts_utc": hours[-1] + ":07:00", "ccy": "TRY", "buy_median": "9999", "source_ok": "False"})
    s = prices_by_source(basis, binance, [], hours[0])
    assert set(s["TRY"]) == {"BTCTurk", "binance_p2p"} and "ARS" not in s, dict(s)
    assert s["TRY"]["binance_p2p"][hours[-1]] == 51.0, "a refused row must not replace the real one"
    doc = build(s, {"TRY": ["BTCTurk"], "AOA": ["binance_p2p", "okx_p2p"], "SDG": ["binance_p2p"]}, "t")
    assert doc["markets"]["TRY"]["one_source"] and doc["markets"]["SDG"]["one_source"]
    assert not doc["markets"]["AOA"]["one_source"]
    assert not doc["markets"]["TRY"]["pairs"][0]["flag"], "an order book and a board differ by design: compared, never flagged"
    a2 = {h: 100.0 for h in hours}; b2 = {h: 104.0 for h in hours}
    d2 = build({"XXX": {"BookA": a2, "BookB": b2}}, {"XXX": ["BookA", "BookB"]}, "t")["markets"]["XXX"]
    assert d2["pairs"][0]["flag"] and d2["pairs"][0]["kind"] == "order_book", "two books 4% apart for 60 hours is a possible finding"
    print("emit_source_pairs self-test: ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    basis, binance, okx = read("basis.csv"), read("p2p_basis.csv"), read("p2p_okx.csv")
    newest = max(r["ts_utc"] for r in binance)
    since = (dt.datetime.fromisoformat(newest) - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H")
    doc = build(prices_by_source(basis, binance, okx, since), feeding_from_countries(), hour_of(newest) + ":00:00Z")
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    one = sum(1 for m in doc["markets"].values() if m["one_source"])
    flagged = sum(1 for m in doc["markets"].values() for p in m["pairs"] if p["flag"])
    print("wrote data/source_pairs.json: %d markets, %d on one source, %d pair(s) flagged" % (len(doc["markets"]), one, flagged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
