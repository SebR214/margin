#!/usr/bin/env python3
"""The claims auditor: every count or absolute claim in reader-facing copy has a
query, and the hourly auditor re-runs it.

claims.json (next to copy.json) lists claims: {key, type, route|..., guards}.
`key` is a path into copy.json ("homeData.stableLine"). For each claim this
script re-derives the fact from the RAW CSVs (it re-runs tools/emit_routes'
own build from the collectors' files, and reads data/basis.csv and
data/p2p_basis.csv directly), never from the published JSON being guarded,
except to check that the figure the sentence prints equals the fresh one.

Output, written every run:
  data/claims_status.json   {as_of_utc, claims: {key: {ok, value, checked, guards}}}
  data/claims_history.csv   append-only: as_of_utc,key,ok,value_json

A claim that is not true gets ok:false. Pages read claims_status.json and do not
render the copy key (nor its `guards`) while it is false. This script NEVER edits
copy.json: the words stay the writer's, the page just drops the line until the
claim is true again or the writer rewrites it.

Claim types:
  stable_never_cheapest  {route, amount?}   hours priced > 0 and hours with the
        stablecoin cheapest == 0 (at any quoted amount, or at `amount`), and the
        published data/routes_summary.json figures for that route equal the fresh
        ones.
  currency_majority_within {pct, min_share}  share of ranked currencies, from the
        last 24 hours of raw rows, whose gap to the official rate is within pct.

Stdlib only, no wall clock (as_of comes from the newest hour in the data).
Usage: python3 tools/audit_claims.py [--self-test]
"""

import csv
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(HERE, "tools"))


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def rows(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            yield r


# ------------------------------------------------------------------ route facts
_FRESH = {}


def fresh_routes():
    if "routes" not in _FRESH:
        import emit_routes
        D, S, docs = emit_routes.build_all()
        cols = docs["hourly"]["hour_columns"]
        i_hour, i_sc = cols.index("hour_utc"), cols.index("stable_cheaper")
        out, last = {}, ""
        for r in docs["hourly"]["routes"]:
            per = {}
            for a in r["amounts"]:
                hs = a["hours"]
                per[a["amount"]] = {"hours": len(hs), "wins": sum(1 for h in hs if h[i_sc])}
                if hs:
                    last = max(last, max(h[i_hour] for h in hs))
            anyhours = {}
            for a in r["amounts"]:
                for h in a["hours"]:
                    k = h[i_hour]
                    anyhours[k] = anyhours.get(k, False) or bool(h[i_sc])
            out[r["id"]] = {"amounts": per, "any_hours": len(anyhours), "any_wins": sum(1 for v in anyhours.values() if v)}
        _FRESH["routes"] = (out, last)
    return _FRESH["routes"]


def claim_stable_never_cheapest(c):
    routes, _ = fresh_routes()
    r = routes.get(c["route"])
    if not r:
        return False, {"reason": "route not in the data"}
    if "amount" in c:
        a = r["amounts"].get(c["amount"]) or {"hours": 0, "wins": 0}
        hours, wins = a["hours"], a["wins"]
    else:
        hours, wins = r["any_hours"], r["any_wins"]
    pub = {}
    try:
        for x in json.load(open(os.path.join(DATA, "routes_summary.json")))["routes"]:
            if x["id"] == c["route"]:
                pub = x
    except (OSError, ValueError, KeyError):
        pass
    printed_hours = pub.get("hours_priced_any_amount")
    printed_wins = pub.get("total_hours_stable_cheapest")
    consistent = "amount" in c or (printed_hours == hours and printed_wins == wins)
    ok = hours > 0 and wins == 0 and consistent
    return ok, {"route": c["route"], "hours_priced": hours, "hours_stablecoin_cheapest": wins,
                "published_hours": printed_hours, "published_wins": printed_wins, "published_matches_fresh": consistent}


# ------------------------------------------------------------- currency facts
def last24_gaps():
    """{ccy: median gap % over the newest 24 hours of raw rows}: order books first, else P2P."""
    book, p2p, newest = {}, {}, ""
    for r in rows("basis.csv"):
        if (r.get("source_ok") or "").strip().lower() != "true" or (r.get("venue") or "").startswith("CriptoYa ("):
            continue
        price = num(r.get("usdt_ask")) or num(r.get("usdt_mid"))
        fx = num(r.get("fx_mid_per_usd"))
        if price and fx:
            book.setdefault(r["ccy"], []).append((r["ts_utc"], (price / fx - 1) * 100))
            newest = max(newest, r["ts_utc"])
    for r in rows("p2p_basis.csv"):
        if (r.get("source_ok") or "").strip().lower() != "true":
            continue
        price, fx = num(r.get("buy_median")), num(r.get("fx_mid_per_usd"))
        if price and fx:
            p2p.setdefault(r["ccy"], []).append((r["ts_utc"], (price / fx - 1) * 100))
            newest = max(newest, r["ts_utc"])
    if not newest:
        return {}, ""
    cutoff = (dt.datetime.fromisoformat(newest) - dt.timedelta(hours=24)).isoformat()
    out = {}
    for src in (p2p, book):  # order books overwrite P2P
        for ccy, vals in src.items():
            v = [g for t, g in vals if t >= cutoff]
            if v:
                out[ccy] = statistics.median(v)
    return out, newest


def claim_currency_majority_within(c):
    gaps, newest = last24_gaps()
    unmaintained = set()
    try:
        for x in json.load(open(os.path.join(DATA, "index_latest.json")))["countries"]:
            if x.get("denominator_class") == "unmaintained":
                unmaintained.add(x["ccy"])
    except (OSError, ValueError, KeyError):
        pass
    ranked = {k: v for k, v in gaps.items() if k not in unmaintained}
    if not ranked:
        return False, {"reason": "no currency has a reading in the last 24 hours"}
    within = sum(1 for v in ranked.values() if abs(v) <= c["pct"])
    share = within / len(ranked)
    return share >= c["min_share"], {"currencies_with_reading": len(ranked), "within_pct": within,
                                     "share": round(share, 3), "pct": c["pct"], "min_share": c["min_share"]}


TYPES = {"stable_never_cheapest": claim_stable_never_cheapest,
         "currency_majority_within": claim_currency_majority_within}


def run():
    claims = json.load(open(os.path.join(HERE, "claims.json")))["claims"]
    results = {}
    for c in claims:
        fn = TYPES.get(c["type"])
        if not fn:
            results[c["key"]] = {"ok": False, "value": {"reason": "unknown claim type " + c["type"]}, "guards": c.get("guards", [])}
            continue
        ok, value = fn(c)
        results[c["key"]] = {"ok": bool(ok), "value": value, "guards": c.get("guards", [])}
    _, last = fresh_routes() if any(c["type"] == "stable_never_cheapest" for c in claims) else (None, "")
    _, newest = last24_gaps()
    as_of = max(last or "", (newest or "")[:13].replace("T", "T") or "")
    return as_of, results


def main():
    as_of, results = run()
    doc = {"as_of_utc": as_of, "claims": results}
    path = os.path.join(DATA, "claims_status.json")
    old = open(path).read() if os.path.exists(path) else ""
    new = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if new != old:
        with open(path, "w") as f:
            f.write(new)
        hist = os.path.join(DATA, "claims_history.csv")
        fresh = not os.path.exists(hist)
        with open(hist, "a", newline="") as f:
            w = csv.writer(f)
            if fresh:
                w.writerow(["as_of_utc", "key", "ok", "value_json"])
            for k, v in sorted(results.items()):
                w.writerow([as_of, k, str(v["ok"]).lower(), json.dumps(v["value"], sort_keys=True, separators=(",", ":"))])
    for k, v in sorted(results.items()):
        print("%s  %s  %s" % ("PASS" if v["ok"] else "FAIL", k, json.dumps(v["value"], sort_keys=True)))
    return 0


def self_test():
    fails = []
    routes, _ = fresh_routes()
    # independent recount of one route from the published hourly file's own rows
    h = json.load(open(os.path.join(DATA, "routes_hourly.json")))
    cols = h["hour_columns"]
    i_sc = cols.index("stable_cheaper")
    for r in h["routes"]:
        for a in r["amounts"]:
            w = sum(1 for x in a["hours"] if x[i_sc])
            if routes[r["id"]]["amounts"][a["amount"]]["wins"] != w:
                fails.append("fresh recount differs: %s %s" % (r["id"], a["amount"]))
    ok, v = claim_stable_never_cheapest({"route": "NO->WHERE"})
    if ok:
        fails.append("unknown route passed")
    ok, v = claim_currency_majority_within({"pct": 0.0000001, "min_share": 0.99})
    if ok:
        fails.append("an impossible majority passed")
    ok, v = claim_currency_majority_within({"pct": 1e9, "min_share": 0.5})
    if not ok:
        fails.append("a trivially true majority failed")
    if fails:
        print("SELF-TEST FAILED: " + "; ".join(fails))
        return 1
    print("self-test ok: fresh route counts match an independent recount; impossible claims fail, trivial ones pass")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
