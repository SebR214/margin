#!/usr/bin/env python3
"""The auditor (SEB-209, ROADMAP Queue item 19): re-derive published numbers
from raw observations and publish the score.

A deterministic script. No model call, no network, stdlib only.

It draws 50 published numbers at random from three families and re-derives
each one from the raw CSVs the collectors wrote -- never from the receipt or
the published JSON being checked, which are the thing under test:

  country   data/countries/<CCY>.json `index_pct`, re-derived from the raw
            price row(s) in data/p2p_basis.csv / data/basis.csv (and, where
            per-ad rows exist, data/p2p_offers.csv) and the official rate in
            the same raw row: (buy price / official rate - 1) * 100.
  corridor  data/corridor_receipts/*.json `cost_bps_taker` / `cost_bps_maker`,
            re-derived from data/samples.csv: (1 - landed / (amount * mid)) * 1e4,
            and the five taker legs must add up to the total.
  variant   data/corridor_variants.csv rows, re-derived the same way against
            the matching data/samples.csv row for the same sample.

A number that cannot be traced to a raw row is a FAILURE, not a skip: "cannot
trace" is exactly what this exists to say out loud.

"Random" is seeded by the newest data date, so the same dataset gives the same
draw and the same score (no wall clock, same rule as every emitter here).
`--seed` overrides it.

Writes data/audit_latest.json and appends one line per audited sample hour to
data/audit_history.csv (append-only, idempotent) -- the series the analyst's
"auditor at 95% for seven straight days" gate reads.

Usage: python3 tools/audit_numbers.py [--dry-run] [--seed S] [--n 50]
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
P2P = os.path.join(DATA, "p2p_basis.csv")
BASIS = os.path.join(DATA, "basis.csv")
OFFERS = os.path.join(DATA, "p2p_offers.csv")
SAMPLES = os.path.join(DATA, "samples.csv")
VARIANTS = os.path.join(DATA, "corridor_variants.csv")
FX = os.path.join(DATA, "fx_rates.csv")
OUT = os.path.join(DATA, "audit_latest.json")
HISTORY = os.path.join(DATA, "audit_history.csv")

PCT_TOL = 0.001      # index_pct is published to 4 dp
BPS_TOL = 0.02       # cost_bps is published to 2 dp
LEG_TOL = 0.011      # five 2-dp legs may drift by rounding only

FAMILIES = ("country", "corridor", "variant")


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ok(v):
    return str(v).strip().lower() == "true"


def hour_of(ts):
    return ts[:13]


def result(item, passed, published, rederived, trace, files, note=""):
    return {
        "id": item["id"], "family": item["family"], "passed": bool(passed),
        "published": published, "rederived": rederived,
        "mismatch": None if passed or published is None or rederived is None
        else round(published - rederived, 6),
        "trace": trace, "files": files, "note": note,
    }


def fail(item, reason, files):
    return result(item, False, None, None, reason, files)


# --------------------------------------------------------------- population
def country_items():
    items = []
    for f in sorted(glob.glob(os.path.join(DATA, "countries", "*.json"))):
        d = json.load(open(f))
        if d.get("index_pct") is None:
            continue
        items.append({"id": "country:%s" % d["ccy"], "family": "country", "doc": d,
                      "file": "data/countries/%s.json" % d["ccy"]})
    return items


def corridor_items():
    items = []
    newest = {}
    for f in sorted(glob.glob(os.path.join(DATA, "corridor_receipts", "*.json"))):
        newest[os.path.basename(f)[:-5].rsplit("_", 1)[0]] = f
    for f in sorted(newest.values()):
        d = json.load(open(f))
        name = os.path.basename(f)[:-5]
        comp = d.get("computation", {})
        for regime in ("taker", "maker"):
            if comp.get(regime, {}).get("result_pct") is not None:
                items.append({"id": "corridor:%s:%s" % (name, regime), "family": "corridor",
                              "doc": d, "regime": regime,
                              "file": "data/corridor_receipts/%s.json" % name})
    return items


def variant_items(variants):
    newest = {}
    for r in variants:
        newest[r["ts"]] = True
    last = sorted(newest)[-1:] or []
    items = []
    for r in variants:
        if r["ts"] in last and ok(r.get("source_ok")):
            items.append({"id": "variant:%s:%s:%s:%s" % (r["corridor"], r["stable"], r["network"], r["notional_src"]),
                          "family": "variant", "row": r, "file": "data/corridor_variants.csv"})
    return items


# ------------------------------------------------------------------- checks
def official_rate(fx_by, ccy, hour, fallback):
    """Newest official rate at or before the price hour (a step function, not
    an hourly observation), else the first one stamped the same day, else the
    rate carried in the price row itself. Re-stated here from the rule in
    METHODOLOGY.md rather than imported from the emitter under test."""
    series = fx_by.get(ccy, [])
    best = None
    for r in series:
        if hour_of(r["ts_utc"]) <= hour:
            best = r
    if best is None:
        same = [r for r in series if r["ts_utc"][:10] == hour[:10]]
        best = same[0] if same else None
    if best is not None and num(best["fx_mid_per_usd"]):
        return num(best["fx_mid_per_usd"]), "data/fx_rates.csv row %s" % best["ts_utc"]
    return fallback, "the price row's own fx column"


def check_country(item, p2p_by, basis_by, offers_by, fx_by):
    d = item["doc"]
    ccy = d["ccy"]
    hour = hour_of(d["hour_utc"])
    pub = d["index_pct"]
    cls = d.get("source_class")
    files = [item["file"], "data/fx_rates.csv"]

    if cls in ("p2p_buy_median", "p2p_fallback"):
        files += ["data/p2p_basis.csv", "data/p2p_offers.csv"]
        hr = [r for r in p2p_by.get(ccy, []) if hour_of(r["ts_utc"]) == hour]
        if not hr:
            return fail(item, "no row in data/p2p_basis.csv for %s in hour %s" % (ccy, hour), files)
        r = hr[0]
        if cls == "p2p_buy_median":
            if not ok(r["source_ok"]):
                return fail(item, "first p2p_basis row for %s in hour %s is not source_ok" % (ccy, hour), files)
            buy = num(r["buy_median"])
            if buy is None:
                return fail(item, "raw row has no buy_median", files)
            offs = offers_by.get((r["ts_utc"], ccy))
            if offs:
                med = statistics.median(offs)
                if abs(med - buy) > 1e-6 * max(1.0, abs(buy)):
                    return result(item, False, buy, med,
                                  "median of %d raw buy offers at %s disagrees with the row's buy_median" % (len(offs), r["ts_utc"]),
                                  files)
            price, src_row = buy, r
        else:
            fb = next((x for x in hr[1:] if ok(x["source_ok"]) and num(x["mid"]) is not None), None)
            if fb is None:
                return fail(item, "no second source_ok row with a mid for %s in hour %s" % (ccy, hour), files)
            price, src_row = num(fb["mid"]), fb
        fx, fx_src = official_rate(fx_by, ccy, hour, num(src_row["fx_mid_per_usd"]))
        if not fx:
            return fail(item, "no official rate for %s" % ccy, files)
        v = (price / fx - 1) * 100
        passed = abs(v - pub) <= PCT_TOL
        return result(item, passed, pub, round(v, 4),
                      "(%s / %s - 1) * 100; price from %s row %s, official rate from %s" % (price, fx, src_row["source"], src_row["ts_utc"], fx_src), files)

    if cls in ("order_book_median", "order_book_single", "broker_median", "broker_single"):
        files += ["data/basis.csv"]
        latest = {}
        for r in basis_by.get(ccy, []):
            is_aggregate = r["venue"].startswith("CriptoYa (") and r["venue"].endswith(")")
            if hour_of(r["ts_utc"]) == hour and ok(r["source_ok"]) and not is_aggregate:
                latest[r["venue"]] = r  # METHODOLOGY: aggregates are listed, never counted
        books = [r for v, r in latest.items() if not v.startswith("CriptoYa:")]
        brokers = [r for v, r in latest.items() if v.startswith("CriptoYa:")]
        chosen = books or brokers
        if not chosen:
            return fail(item, "no source_ok row in data/basis.csv for %s in hour %s" % (ccy, hour), files)
        prices = []
        for r in chosen:
            p = num(r["usdt_ask"]) or num(r["usdt_mid"])
            if p is None:
                return fail(item, "raw %s row has neither usdt_ask nor usdt_mid" % r["venue"], files)
            prices.append(p)
        price = statistics.median(prices)
        fx, fx_src = official_rate(fx_by, ccy, hour, num(chosen[0]["fx_mid_per_usd"]))
        if not fx:
            return fail(item, "no official rate for %s" % ccy, files)
        v = (price / fx - 1) * 100
        passed = abs(v - pub) <= PCT_TOL
        return result(item, passed, pub, round(v, 4),
                      "median of %d %s price(s) = %s over official rate %s (%s)" % (
                          len(prices), "order book" if books else "broker", round(price, 6), fx, fx_src), files)

    return fail(item, "source_class %r has no raw re-derivation implemented" % cls, files)


def check_corridor(item, samples_by):
    d = item["doc"]
    regime = item["regime"]
    comp = d["computation"][regime]
    pub_bps = comp["result_pct"]
    corridor = d["corridor"]
    ts = d["evidence"]["collected_at"]
    notional = None
    for k in ("notional_src", "notional"):
        if d.get(k) is not None:
            notional = d[k]
    files = [item["file"], "data/samples.csv"]
    cand = [r for r in samples_by.get(corridor, []) if r["ts"] == ts]
    if notional is not None:
        cand = [r for r in cand if num(r["notional_src"]) == num(notional)]
    if not cand:
        return fail(item, "no data/samples.csv row for %s at %s" % (corridor, ts), files)
    if len(cand) > 1:
        return fail(item, "%d samples.csv rows match %s at %s; cannot tell which one this receipt is" % (len(cand), corridor, ts), files)
    r = cand[0]
    amount, mid = num(r["notional_src"]), num(r["mid_src_dst"])
    landed = num(r["landed_" + regime])
    if not amount or not mid or landed is None:
        return fail(item, "raw sample row is missing notional / mid / landed", files)
    bps = (1 - landed / (amount * mid)) * 1e4
    passed = abs(bps - pub_bps) <= BPS_TOL
    note = ""
    if passed and regime == "taker" and comp.get("legs_available"):
        legs = comp["legs"]
        total = sum(legs[k] for k in ("deposit_bps", "buy_bps", "move_bps", "sell_bps", "withdrawal_bps"))
        if abs(total - pub_bps) > LEG_TOL:
            passed = False
            note = "legs add to %s, total is %s" % (round(total, 4), pub_bps)
    return result(item, passed, pub_bps, round(bps, 2),
                  "(1 - %s / (%s * %s)) * 10000 from samples.csv row %s" % (landed, amount, mid, ts), files, note)


def check_variant(item, samples_by):
    r = item["row"]
    files = [item["file"], "data/samples.csv"]
    cand = [s for s in samples_by.get(r["corridor"], [])
            if hour_of(s["ts"]) == hour_of(r["ts"]) and num(s["notional_src"]) == num(r["notional_src"])]
    if len(cand) != 1:
        return fail(item, "%d matching data/samples.csv row(s) for this variant's hour and amount; its cost cannot be re-derived" % len(cand), files)
    amount, mid = num(cand[0]["notional_src"]), num(cand[0]["mid_src_dst"])
    out = []
    ok_all = True
    for regime in ("taker", "maker"):
        landed, pub = num(r["landed_" + regime]), num(r["cost_bps_" + regime])
        if landed is None or pub is None or not mid:
            return fail(item, "raw variant row missing landed / cost", files)
        bps = (1 - landed / (amount * mid)) * 1e4
        out.append((regime, pub, round(bps, 2)))
        ok_all = ok_all and abs(bps - pub) <= BPS_TOL
    return result(item, ok_all, out[0][1], out[0][2],
                  "; ".join("%s %s vs %s" % o for o in out), files)


def stratified(items, n, rng):
    """Even shares per family so one big family cannot crowd out the others;
    a family smaller than its share gives the slack to the rest."""
    pools = {f: [i for i in items if i["family"] == f] for f in FAMILIES}
    pools = {f: p for f, p in pools.items() if p}
    take = {f: 0 for f in pools}
    left = min(n, sum(len(p) for p in pools.values()))
    while left > 0:
        open_ = [f for f in pools if take[f] < len(pools[f])]
        for f in open_:
            if left == 0:
                break
            take[f] += 1
            left -= 1
    out = []
    for f in sorted(pools):
        out += rng.sample(pools[f], take[f])
    return out


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    ap.add_argument("--seed")
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()

    samples = rows(SAMPLES)
    variants = rows(VARIANTS)
    if not samples:
        print("audit: data/samples.csv is empty or missing", file=sys.stderr)
        return 1
    newest = max(r["ts"] for r in samples)
    as_of_date = newest[:10]
    seed = a.seed or as_of_date

    samples_by = {}
    for r in samples:
        if ok(r.get("source_ok")):
            samples_by.setdefault(r["corridor"], []).append(r)

    items = country_items() + corridor_items() + variant_items(variants)
    items.sort(key=lambda i: i["id"])
    drawn = stratified(items, a.n, random.Random(seed))

    need_p2p = {i["doc"]["ccy"] for i in drawn if i["family"] == "country" and i["doc"].get("source_class") in ("p2p_buy_median", "p2p_fallback")}
    need_book = {i["doc"]["ccy"] for i in drawn if i["family"] == "country" and i["doc"].get("source_class") not in (None, "p2p_buy_median", "p2p_fallback")}
    p2p_by, basis_by, offers_by, fx_by = {}, {}, {}, {}
    need_fx = {i["doc"]["ccy"] for i in drawn if i["family"] == "country"}
    for r in rows(FX):
        if r["ccy"] in need_fx:
            fx_by.setdefault(r["ccy"], []).append(r)
    for r in rows(P2P):
        if r["ccy"] in need_p2p:
            p2p_by.setdefault(r["ccy"], []).append(r)
    for r in rows(BASIS):
        if r["ccy"] in need_book:
            basis_by.setdefault(r["ccy"], []).append(r)
    if need_p2p and os.path.exists(OFFERS):
        with open(OFFERS, newline="") as f:
            for r in csv.DictReader(f):
                if r["ccy"] in need_p2p and r["side"] == "buy":
                    p = num(r["price"])
                    if p is not None:
                        offers_by.setdefault((r["ts_utc"], r["ccy"]), []).append(p)

    results = []
    for it in drawn:
        if it["family"] == "country":
            results.append(check_country(it, p2p_by, basis_by, offers_by, fx_by))
        elif it["family"] == "corridor":
            results.append(check_corridor(it, samples_by))
        else:
            results.append(check_variant(it, samples_by))

    passed = sum(1 for r in results if r["passed"])
    by_family = {}
    for fam in FAMILIES:
        rs = [r for r in results if r["family"] == fam]
        by_family[fam] = {"drawn": len(rs), "passed": sum(1 for r in rs if r["passed"]),
                          "population": sum(1 for i in items if i["family"] == fam)}
    out = {
        "as_of_date": as_of_date,
        "sample_ts": newest,
        "seed": seed,
        "population": len(items),
        "drawn": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "score_pct": round(100.0 * passed / len(results), 1) if results else None,
        "by_family": by_family,
        "families_not_yet_audited": ["price changes", "provider rankings", "provider delivery times"],
        "failures": [r for r in results if not r["passed"]],
        "passes": [{k: r[k] for k in ("id", "family", "published", "rederived")} for r in results if r["passed"]],
    }
    text = json.dumps(out, indent=1, sort_keys=True)
    if a.dry_run:
        print(text)
        return 0
    with open(OUT, "w") as f:
        f.write(text + "\n")
    # Append-only, one line per audited sample hour (idempotent: a re-run on
    # the same data adds nothing). The analyst's "95% for seven straight days"
    # gate reads the worst score of each day from this file.
    hist = rows(HISTORY)
    if not any(h["sample_ts"] == newest for h in hist):
        new = not os.path.exists(HISTORY)
        with open(HISTORY, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["sample_ts", "date", "drawn", "passed", "score_pct"])
            w.writerow([newest, as_of_date, out["drawn"], passed, out["score_pct"]])
    print("audit %s: %d/%d re-derived (%.1f%%)" % (as_of_date, passed, len(results), out["score_pct"] or 0))
    for fam, v in by_family.items():
        print("  %-9s %d/%d of %d in population" % (fam, v["passed"], v["drawn"], v["population"]))
    for r in out["failures"][:8]:
        print("  FAIL %s: %s" % (r["id"], r["trace"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
