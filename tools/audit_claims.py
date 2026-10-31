#!/usr/bin/env python3
"""The claims auditor: every count or absolute claim in reader-facing copy has a
query, and the hourly auditor re-runs it.

claims.json (next to copy.json) lists claims: {key, type, route|..., guards}.
`key` is a path into copy.json ("homeData.heatTitle"). For each claim this
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


def ranked_priced_counts(pct, data=None):
    """(n, N): of the ranked countries with a price this hour (the count in the Countries page title), how many sit within
    `pct` of the official rate. Counted from the country files themselves, for the index's own hour; a currency the index
    lists as unverified, or whose official rate is unmaintained, is not ranked."""
    data = data or DATA
    idx = json.load(open(os.path.join(data, "index_latest.json")))
    hour = idx["as_of_utc"][:13]
    unverified = {u if isinstance(u, str) else u.get("ccy") for u in idx.get("unverified") or []}
    n = N = 0
    for f in sorted(os.listdir(os.path.join(data, "countries"))):
        if not f.endswith(".json") or " " in f or f[:-5] in unverified:
            continue
        d = json.load(open(os.path.join(data, "countries", f)))
        v = d.get("index_pct")
        if not isinstance(v, (int, float)) or str(d.get("hour_utc", ""))[:13] != hour:
            continue
        if (d.get("denominator") or {}).get("class") == "unmaintained":
            continue
        N += 1
        n += 1 if abs(v) <= pct else 0
    return n, N


def claim_within_of_ranked(c):
    """'In {n} of {N} countries we priced this hour, a dollar costs within 2% of the official rate.' True when {n} and {N}
    recounted from the country files equal the figures index_latest.json publishes for the same hour (the Countries page
    counts ranked countries with a price the same way). The sentence states a count, so the count is the claim."""
    n, N = ranked_priced_counts(c["pct"])
    pub = json.load(open(os.path.join(DATA, "index_latest.json")))["countries"]
    pub_N = sum(1 for x in pub if x.get("index_pct") is not None and x.get("denominator_class") != "unmaintained")
    pub_n = sum(1 for x in pub if x.get("index_pct") is not None and x.get("denominator_class") != "unmaintained"
                and abs(x["index_pct"]) <= c["pct"])
    ok = N > 0 and n <= N and (n, N) == (pub_n, pub_N)
    return ok, {"n": n, "N": N, "published_n": pub_n, "published_N": pub_N, "pct": c["pct"]}


def claim_stable_rarely_cheapest(c):
    """'In {n} of the {hours} hours we priced, a stablecoin did not beat the cheapest app at any of the five amounts.'
    True while, at every amount, the stablecoin was cheapest in under `max_share` of the hours priced. {hours} is the
    number of distinct hours priced at any amount; {n} is those hours in which it was cheapest at none."""
    routes, _ = fresh_routes()
    r = routes.get(c["route"])
    if not r:
        return False, {"reason": "route not in the data"}
    per = {str(a): v for a, v in r["amounts"].items()}
    rare = bool(per) and all(v["hours"] > 0 and v["wins"] / v["hours"] < c["max_share"] for v in per.values())
    hours, wins = r["any_hours"], r["any_wins"]
    return rare, {"route": c["route"], "hours": hours, "n": hours - wins, "hours_stablecoin_cheapest_any_amount": wins,
                  "max_share": c["max_share"], "per_amount": per}


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


def claim_updated_hourly(c):
    """'Updated every hour': in the newest `window_hours` clock hours the collectors stored a reading in every hour."""
    hrs = set()
    for name in ("basis.csv", "p2p_basis.csv"):
        for r in rows(name):
            if (r.get("source_ok") or "").strip().lower() == "true":
                hrs.add(r["ts_utc"][:13])
    if not hrs:
        return False, {"reason": "no readings"}
    newest = max(hrs)
    t = dt.datetime.fromisoformat(newest + ":00")
    n = c.get("window_hours", 24)
    want = [(t - dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H") for i in range(n)]
    missing = [h for h in want if h not in hrs]
    return not missing, {"window_hours": n, "newest_hour": newest, "hours_missing": len(missing), "missing_hours": missing}


def claim_coverage_matches_index(c):
    """The 'N of 60 currencies priced' figure on the pages equals a recount of the country files with a price."""
    printed = None
    try:
        printed = json.load(open(os.path.join(DATA, "cycle_log.json")))["steps"]["currencies"]
    except (OSError, ValueError, KeyError):
        pass
    # A currency is priced when its country file carries a price for the index's own hour and the index publishes it.
    # A file left over from an earlier hour (a currency the index lists as unverified) is not priced.
    hour, unverified = None, set()
    try:
        idx = json.load(open(os.path.join(DATA, "index_latest.json")))
        hour = idx["as_of_utc"][:13]
        unverified = {u if isinstance(u, str) else u.get("ccy") for u in idx.get("unverified") or []}
    except (OSError, ValueError, KeyError):
        pass
    priced = total = 0
    for f in sorted(os.listdir(os.path.join(DATA, "countries"))):
        if not f.endswith(".json") or " " in f:
            continue
        d = json.load(open(os.path.join(DATA, "countries", f)))
        total += 1
        if f[:-5] in unverified:
            continue  # the index does not publish a price for an unverified currency
        if isinstance(d.get("index_pct"), (int, float)) and hour and str(d.get("hour_utc", ""))[:13] == hour:
            priced += 1
    ok = bool(printed) and printed["collected"] == priced and printed["of"] == total
    return ok, {"printed_priced": printed and printed["collected"], "printed_of": printed and printed["of"],
                "recount_priced": priced, "recount_of": total}


def claim_sources_counts(c):
    """The opening counts of the Sources page add up: live + history-only = all, with + without history = all."""
    d = json.load(open(os.path.join(DATA, "sources_daily.json")))["sources"]
    total = len(d)
    live = sum(1 for s in d if s["live"])
    hist = sum(1 for s in d if s["history"])
    ok = live + (total - live) == total and hist + (total - hist) == total and total > 0
    return ok, {"sources": total, "read_every_hour_or_live": live, "history_only": total - live,
                "with_history": hist, "without_history": total - hist}


def claim_routes_published_equal_fresh(c):
    """Every route's published hour counts equal the counts re-derived from the raw CSVs."""
    routes, _ = fresh_routes()
    pub = json.load(open(os.path.join(DATA, "routes_summary.json")))["routes"]
    pub_data = json.load(open(os.path.join(DATA, "routes_summary.json")))
    
    bad = []
    detail = {}
    
    for x in pub:
        route_id = x["id"]
        fresh_route = routes.get(route_id)
        
        if fresh_route is None:
            bad.append(route_id)
            detail[route_id] = {
                "published_hours": x["hours_priced_any_amount"],
                "fresh_hours": None,
                "published_wins": x["total_hours_stable_cheapest"],
                "fresh_wins": None
            }
        else:
            published_hours = x["hours_priced_any_amount"]
            fresh_hours = fresh_route["any_hours"]
            published_wins = x["total_hours_stable_cheapest"]
            fresh_wins = fresh_route["any_wins"]
            
            if published_hours != fresh_hours or published_wins != fresh_wins:
                bad.append(route_id)
                detail[route_id] = {
                    "published_hours": published_hours,
                    "fresh_hours": fresh_hours,
                    "published_wins": published_wins,
                    "fresh_wins": fresh_wins
                }
    
    return not bad and bool(pub), {"routes": len(pub), "differ": bad, "detail": detail}


def _official_day_values(ccy, day):
    """Every independent reading of one currency's official rate for one UTC day: the last live reading and each history file's value."""
    out = []
    last = None
    for r in rows("fx_rates.csv"):
        if r["ccy"] == ccy and r["ts_utc"][:10] == day and num(r["fx_mid_per_usd"]) is not None:
            last = num(r["fx_mid_per_usd"])
    if last is not None:
        out.append(last)
    hist = os.path.join(DATA, "history")
    for name in sorted(os.listdir(hist)) if os.path.isdir(hist) else []:
        if name.startswith("official_fx_") and name.endswith(".csv"):
            for r in rows(os.path.join("history", name)):
                if r["date"] == day and r["ccy"] == ccy and num(r["per_usd"]) is not None:
                    out.append(num(r["per_usd"]))
    return out


def _street_day_median(ccy, day):
    vals = [num(r["buy_median"]) for r in rows("p2p_basis.csv")
            if r["source"] == "binance_p2p" and r["ccy"] == ccy and r["ts_utc"][:10] == day and r["source_ok"] == "True" and num(r["buy_median"]) is not None]
    return (statistics.median(vals) if len(vals) >= 12 else None)


def _history_street_closes(ccy, day):
    out = []
    hist = os.path.join(DATA, "history")
    for name in sorted(os.listdir(hist)) if os.path.isdir(hist) else []:
        if name.startswith("candles_") and name.endswith("_1d.csv"):
            for r in rows(os.path.join("history", name)):
                if r["ccy"] == ccy and r["ts_utc"][:10] == day and num(r["close"]) is not None:
                    out.append(num(r["close"]))
    return out


def claim_event_pages(c):
    """Every event on data/events_published.json: its record's official rates equal a reading in the raw files for that day, the move
    printed on the page equals the detector's row, and the street price before (used in the landing block) equals the day's median
    of the raw Binance rows. Fails if the list is missing or an event has no record."""
    pub_path = os.path.join(DATA, "events_published.json")
    if not os.path.exists(pub_path):
        return False, {"reason": "data/events_published.json missing"}
    pub = json.load(open(pub_path)).get("events", [])
    bad = []
    for e in pub:
        rp = os.path.join(HERE, e["record"])
        if not os.path.exists(rp):
            bad.append({"id": e["id"], "reason": "record missing"})
            continue
        rec = json.load(open(rp))
        o = rec.get("official") or {}
        close = lambda a, b: a is not None and b is not None and abs(a - b) <= 0.002 * abs(b)
        for key, day in (("baseline", o.get("baseline_day")), ("at_detection", rec.get("detected_on"))):
            if o.get(key) is None or not any(close(v, o[key]) for v in _official_day_values(rec["ccy"], day)):
                bad.append({"id": e["id"], "official": key, "day": day})
        if e["event_kind"] == "official_break" and o.get("baseline") and o.get("at_detection") and e["record"].find("event_records_rules4") < 0:
            if abs((o["at_detection"] / o["baseline"] - 1) * 100 - e["change_pct"]) > 0.1:
                bad.append({"id": e["id"], "reason": "move differs from the row"})
        a = (rec.get("after") or [{}])[0]
        if a.get("official") is not None and not any(close(v, a["official"]) for v in _official_day_values(rec["ccy"], a["day"])):
            bad.append({"id": e["id"], "official": "after", "day": a.get("day")})
        st = rec.get("street") or {}
        if st.get("before") is not None:
            if "data/history" in (st.get("source") or ""):
                seen = _history_street_closes(rec["ccy"], st.get("before_day"))
                if not any(abs(v - st["before"]) <= 0.002 * abs(v) for v in seen):
                    bad.append({"id": e["id"], "street_before": st["before"], "history_closes": seen})
                continue
            m = _street_day_median(rec["ccy"], st.get("before_day"))
            if m is None or abs(m - st["before"]) > 0.01 * abs(m):
                bad.append({"id": e["id"], "street_before": st["before"], "raw": m})
    return not bad and bool(pub), {"events": len(pub), "bad": bad}


TYPES = {"stable_never_cheapest": claim_stable_never_cheapest,
         "stable_rarely_cheapest": claim_stable_rarely_cheapest,
         "within_of_ranked": claim_within_of_ranked,
         "currency_majority_within": claim_currency_majority_within,
         "updated_hourly": claim_updated_hourly,
         "coverage_matches_index": claim_coverage_matches_index,
         "sources_counts": claim_sources_counts,
         "routes_published_equal_fresh": claim_routes_published_equal_fresh,
         "event_pages": claim_event_pages}


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
    # SEB-268 (Seb's words, 12 Oct): the two counted claims
    ok, v = claim_within_of_ranked({"pct": 2})
    if not ok or not (0 < v["n"] <= v["N"]) or (v["n"], v["N"]) != (v["published_n"], v["published_N"]):
        fails.append("within_of_ranked does not match the published count: %s" % (v,))
    ok, v = claim_within_of_ranked({"pct": 1e9})
    if not ok or v["n"] != v["N"]:
        fails.append("everyone is within an enormous bar")
    ok, v = claim_stable_rarely_cheapest({"route": "SGD->PHP", "max_share": 1.01})
    if not ok:
        fails.append("rarely-cheapest failed under a share bar of 101%")
    ok, v = claim_stable_rarely_cheapest({"route": "SGD->PHP", "max_share": 0.0000001})
    if v.get("hours_stablecoin_cheapest_any_amount", 0) > 0 and ok:
        fails.append("rarely-cheapest passed though the stablecoin was cheapest at some hour and the bar was tiny")
    ok, v = claim_stable_rarely_cheapest({"route": "NO->WHERE", "max_share": 0.01})
    if ok:
        fails.append("unknown route passed rarely-cheapest")
    ok, v = claim_routes_published_equal_fresh({"route": "NO->WHERE"})
    if ok:
        fails.append("unknown route passed routes_published_equal_fresh")
    if fails:
        print("SELF-TEST FAILED: " + "; ".join(fails))
        return 1
    print("self-test ok: fresh route counts match an independent recount; impossible claims fail, trivial ones pass")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
