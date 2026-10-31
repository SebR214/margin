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


# ------------------------------------------------------------------ home sentences (SEB-423)
def _hourly_series():
    """{ccy: {hour_text: value}} read straight from the raw hourly file, a second reader apart from tools/emit_home_facts.py."""
    out = {}
    for r in rows("index_hourly.csv"):
        v = num(r["index_pct"])
        if v is not None:
            out.setdefault(r["ccy"], {})[r["hour_utc"]] = v
    return out


def _hour(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def claim_home_largest_move(c):
    """The headline names the country whose gap moved most in 24 hours. Re-derived from data/index_hourly.csv with its own loop and
    compared with data/home_facts.json: same country, same points, same direction, same 'since' date. When the file says no country
    moved more than one point, the claim holds only if the raw rows agree."""
    facts_path = os.path.join(DATA, "home_facts.json")
    if not os.path.exists(facts_path):
        return False, {"reason": "data/home_facts.json missing"}
    facts = json.load(open(facts_path))
    pub = facts.get("largest_move")
    ser = _hourly_series()
    if not ser:
        return False, {"reason": "no hourly rows"}
    newest = max(_hour(h) for v in ser.values() for h in v)
    if facts.get("as_of_utc") and _hour(facts["as_of_utc"]) != newest:
        return False, {"reason": "home_facts.json is not for the newest hour", "facts": facts.get("as_of_utc"), "raw": newest.isoformat()}
    ranked = set()
    for x in (json.load(open(os.path.join(DATA, "index_latest.json"))).get("countries", [])):
        if x.get("index_pct") is not None and x.get("denominator_class") != "unmaintained":
            ranked.add(x["ccy"])
    top = None
    for ccy in sorted(ranked):
        pts = {_hour(h): v for h, v in ser.get(ccy, {}).items()}
        if newest not in pts:
            continue
        older = [t for t in pts if t <= newest - dt.timedelta(hours=24) and newest - dt.timedelta(hours=24) - t <= dt.timedelta(hours=3)]
        if not older:
            continue
        d = pts[newest] - pts[max(older)]
        if top is None or abs(d) > abs(top[1]):
            top = (ccy, d, pts)
    fresh = None
    if top and abs(top[1]) > 1.0:
        ccy, d, pts = top
        window = sorted((t, v) for t, v in pts.items() if newest - dt.timedelta(days=30) <= t <= newest)
        vals = sorted(v for _, v in window)
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        side = (pts[newest] > med) - (pts[newest] < med)
        since = None
        if side:
            run = newest
            for t, v in reversed(window):
                if ((v > med) - (v < med)) != side:
                    break
                run = t
            since = run.date().isoformat()
        fresh = {"ccy": ccy, "points": round(abs(d), 1), "direction": "dearer" if d > 0 else "cheaper", "since": since}
    if fresh is None:
        return pub is None, {"raw": None, "published": pub and pub.get("ccy")}
    if not pub:
        return False, {"raw": fresh, "published": None}
    same = all(pub.get(k) == fresh[k] for k in fresh)
    return same, {"raw": fresh, "published": {k: pub.get(k) for k in fresh}}


def claim_home_what_changed(c):
    """Each line in the what-changed block is checked against the file it came from, and the list is checked for order and size."""
    facts_path = os.path.join(DATA, "home_facts.json")
    if not os.path.exists(facts_path):
        return False, {"reason": "data/home_facts.json missing"}
    facts = json.load(open(facts_path))
    items = facts.get("what_changed", [])
    bad = []
    if len(items) > 8 or [i["date"] for i in items] != sorted((i["date"] for i in items), reverse=True):
        bad.append("order or size")
    heat = json.load(open(os.path.join(DATA, "heatmap_daily.json")))
    reg = json.load(open(os.path.join(DATA, "source_registry.json"))).get("sources", {})
    for it in items:
        k = it["kind"]
        if k in ("crossed_up", "crossed_down"):
            cur = next((x for x in heat["currencies"] if x["ccy"] == it["ccy"]), None)
            i = heat["days"].index(it["date"]) if it["date"] in heat["days"] else -1
            a, b = (cur["cells"][i - 1], cur["cells"][i]) if cur and i > 0 else (None, None)
            up = a is not None and b is not None and a < 5 <= b
            down = a is not None and b is not None and a >= 5 > b
            if not ((k == "crossed_up" and up) or (k == "crossed_down" and down)) or round(b, 1) != it["pct"]:
                bad.append({"item": k, "ccy": it["ccy"], "date": it["date"]})
        elif k == "source_added":
            s = reg.get(it["source"])
            if not s or s.get("first_row") != it["date"] or s.get("status") != it["status"]:
                bad.append({"item": k, "source": it["source"]})
        elif k == "event":
            row = None
            for name in ("events.csv", os.path.join("history", "events_reported_rules4.csv")):
                for r in rows(name):
                    if r["event_id"] == it["id"] and r["status"] == "candidate":
                        row = r
            if not row or round(abs(num(row["change_pct"])), 1) != it["pct"] or row["confirmation"] != "two sources":
                bad.append({"item": k, "id": it["id"]})
        elif k == "finding_changed":
            seen = {}
            for r in rows("finding_tests.csv"):
                if r["finding_id"] == it["id"]:
                    seen[r["ts_utc"][:10]] = r["status"]
            days = sorted(seen)
            ok = it["date"] in seen and days.index(it["date"]) > 0 and seen[days[days.index(it["date"]) - 1]] == it["from"] and seen[it["date"]] == it["to"]
            if not ok:
                bad.append({"item": k, "id": it["id"]})
        elif k == "route_flip":
            h = json.load(open(os.path.join(DATA, "routes_hourly.json")))
            ih, ic = h["hour_columns"].index("hour_utc"), h["hour_columns"].index("stable_cheaper")
            r = next((x for x in h["routes"] if x["id"] == it["route"]), None)
            a = next((x for x in r["amounts"] if x["amount"] == it["amount"]), None) if r else None
            if not a:
                bad.append({"item": k, "route": it["route"]})
                continue
            day = {}
            for row in a["hours"]:
                day.setdefault(row[ih][:10], []).append(bool(row[ic]))
            prev = (dt.date.fromisoformat(it["date"]) - dt.timedelta(days=1)).isoformat()
            if it["date"] not in day or prev not in day or len(day[it["date"]]) < 12 or len(day[prev]) < 12:
                bad.append({"item": k, "route": it["route"], "reason": "day missing"})
                continue
            now, before = sum(day[it["date"]]) * 2 > len(day[it["date"]]), sum(day[prev]) * 2 > len(day[prev])
            if now == before or ("cheaper" if now else "dearer") != it["now"]:
                bad.append({"item": k, "route": it["route"]})
        else:
            bad.append({"item": k, "reason": "unknown kind"})
    return not bad, {"items": len(items), "bad": bad}

# ------------------------------------------------------------------ Research pages (SEB-423 step 3)
def claim_research_pairs(c):
    """'Markets inside one country disagree': the page's counts and rows (data/research/source_pairs.json) re-derived from
    data/source_pairs.json with a separate loop: the countries compared, the three bands, and each country's furthest-apart pair."""
    pub_path = os.path.join(DATA, "research", "source_pairs.json")
    if not os.path.exists(pub_path):
        return False, {"reason": "data/research/source_pairs.json missing"}
    pub = json.load(open(pub_path))
    raw = json.load(open(os.path.join(DATA, "source_pairs.json")))
    worst = {}
    for ccy, m in raw["markets"].items():
        for p in m.get("pairs", []):
            if p["hours"] >= raw["min_common_hours"] and p.get("median_gap_pct") is not None:
                if ccy not in worst or p["median_gap_pct"] > worst[ccy]["median_gap_pct"]:
                    worst[ccy] = p
    fresh_bands = {"tight": sum(1 for p in worst.values() if p["median_gap_pct"] <= 0.5),
                   "middle": sum(1 for p in worst.values() if 0.5 < p["median_gap_pct"] < 3.0),
                   "wide": sum(1 for p in worst.values() if p["median_gap_pct"] >= 3.0)}
    shown = {r["ccy"]: r for r in pub["countries"]}
    bad = [k for k, r in shown.items() if k not in worst or round(worst[k]["median_gap_pct"], 4) != round(r["gap_pct"], 4) or worst[k]["hours"] != r["hours"]]
    ok = pub["compared"] == len(worst) == len(shown) and pub["bands"] == fresh_bands and not bad
    return ok, {"compared": len(worst), "published": pub["compared"], "bands": fresh_bands, "published_bands": pub["bands"], "differ": bad}


def claim_research_months(c):
    """The live months on the capital controls page: each (country, month) re-derived from data/index_hourly.csv, a day's value the median
    of its hourly values (12 or more hours), a month's value the median of its days (5 or more days)."""
    pub_path = os.path.join(DATA, "research", "capital_controls_months.json")
    if not os.path.exists(pub_path):
        return False, {"reason": "data/research/capital_controls_months.json missing"}
    pub = json.load(open(pub_path))
    per = {}
    for r in rows("index_hourly.csv"):
        v = num(r["index_pct"])
        if v is not None:
            per.setdefault(r["ccy"], {}).setdefault(r["hour_utc"][:10], []).append(v)
    fresh = {}
    for ccy, days in per.items():
        months = {}
        for d, vs in days.items():
            if len(vs) >= 12:
                months.setdefault(d[:7], []).append(statistics.median(vs))
        for m, vs in months.items():
            if len(vs) >= 5:
                fresh[(ccy, m)] = (round(statistics.median(vs), 2), len(vs))
    shown = {(r["ccy"], r["month"]): (r["median_premium_pct"], r["days"]) for r in pub["months"]}
    return shown == fresh and bool(shown), {"months": len(fresh), "published": len(shown),
                                            "differ": sorted(str(k) for k in set(shown) ^ set(fresh) | {k for k in shown if k in fresh and shown[k] != fresh[k]})[:10]}


TYPES = {"stable_never_cheapest": claim_stable_never_cheapest,
         "stable_rarely_cheapest": claim_stable_rarely_cheapest,
         "within_of_ranked": claim_within_of_ranked,
         "currency_majority_within": claim_currency_majority_within,
         "updated_hourly": claim_updated_hourly,
         "coverage_matches_index": claim_coverage_matches_index,
         "sources_counts": claim_sources_counts,
         "routes_published_equal_fresh": claim_routes_published_equal_fresh,
         "home_largest_move": claim_home_largest_move,
         "home_what_changed": claim_home_what_changed,
         "research_pairs": claim_research_pairs,
         "research_months": claim_research_months}


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
