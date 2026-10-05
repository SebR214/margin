#!/usr/bin/env python3
"""Data emitters for the routes page (SEB-240). Stored files in, JSON out.

Reads files already in data/ and writes four JSON files the page fetches:

  data/routes_hourly.json     per route and amount, one row per priced hour
  data/routes_summary.json    counts, medians, swing, 7-day change, extremes
  data/routes_breakdown.json  the stablecoin path split into its stored legs
  data/routes_whatif.json     how much cheaper in+out must be to match the app

No new service, no model call, no wall clock, no estimate. A value that is not
stored is null (or the hour is omitted), never filled or carried forward.
There are no prose fields: ids and labels are exactly as stored, amounts and
costs are numbers, `gaps` rows carry reason codes.

DEFINITIONS (shared by all four files)

  hour            the UTC clock hour (ts[:13]) -- the same key
                  tools/emit_corridor_history.py uses. Within an hour the LAST
                  stored observation is used (rows are append-only, so file
                  order is time order; tools/emit_providers.py overwrites the
                  same way). One rule, so a breakdown always sums to its total.
  stable_cost     what the recipient loses against the real exchange rate, in
                  sending-currency units, for the cheapest stablecoin path
                  stored that hour = amount * cost_bps_taker / 1e4 (taker,
                  market order, all fees in, mid-market rate as the
                  reference: collector.py decompose(), the same figure
                  corridor.html calls "Stablecoin, market order").
  stable_cost_pct that, as a share of the amount (= cost_bps_taker / 100).
  stable_path     the stored id of the path: the base route's stablecoin from
                  data/samples.csv (e.g. "USDT"), or "<stable>:<network>" from
                  data/corridor_variants.csv (e.g. "USDC:ArbitrumOne"). The
                  cheapest one stored that hour; ties go to the base route.
                  This is corridor.html routePricing()'s "cheapest of N".
  app_cost        same loss, same units, for the cheapest app that hour: every
                  provider's all-in cost, taken from the provider's own quote
                  (data/provider_quotes.csv) where it published one and from the
                  public comparison panel (data/providers*.csv) otherwise --
                  tools/emit_providers.py's precedence rule -- then the
                  minimum. `app_source` says which source the cheapest used.
  feed_cost_pct   the comparison feed's best price (samples.csv
                  baseline_cost_bps / 100, provider in `feed_app`): the figure
                  the homepage and corridor_history.json call "cheapest app".
                  Carried beside app_cost so the page can pick one on purpose.
  stable_cheaper  stable_cost_pct < app_cost_pct (strict).
  extra cost      stable minus app, in cost units and in percentage points of
                  the amount; negative when the stablecoin path is cheaper.
  priced hour     an hour with both a stablecoin price and an app price.
                  Hours missing either are omitted, not filled.

Usage:
  python3 tools/emit_routes.py              # write the four files
  python3 tools/emit_routes.py --self-test  # offline checks on the stored data

Stdlib only.
"""

import csv
import datetime as dt
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")

SAMPLES = "samples.csv"
VARIANTS = "corridor_variants.csv"
QUOTES = "provider_quotes.csv"
WATERFALL = "corridor_waterfall.csv"
RAMP_WATERFALL = "ramp_waterfall.csv"
RAMP_FEES = "ramp_fees.csv"
WITHDRAWAL_FEES = "withdrawal_fees.csv"
# Each route's comparison panel lives in its own file (providers.csv has no
# corridor column): same map as tools/emit_providers.py PANELS.
PANELS = {
    "SGD->PHP": "providers.csv",
    "USD->MXN": "providers_usdmxn.csv",
    "AUD->PHP": "providers_audphp.csv",
    "NZD->PHP": "providers_nzdphp.csv",
    "USD->NGN": "providers_usdngn.csv",
    "USD->INR": "providers_usdinr.csv",
    "SGD->INR": "providers_sgdinr.csv",
}
# Order as tools/emit_corridor_summary.py CORRIDORS.
ROUTES = ["SGD->PHP", "AUD->PHP", "NZD->PHP", "USD->MXN",
          "USD->NGN", "USD->INR", "SGD->INR"]
START = "2026-08-10"          # the first stored hour of any route
DEFAULT_AMOUNT = 5000         # tools/emit_corridor_summary.py RUNG
WINDOW_DAYS = 7

OUT = {
    "hourly": os.path.join(DATA, "routes_hourly.json"),
    "summary": os.path.join(DATA, "routes_summary.json"),
    "breakdown": os.path.join(DATA, "routes_breakdown.json"),
    "whatif": os.path.join(DATA, "routes_whatif.json"),
}

DEFINITION = {
    "hour": "UTC clock hour; the last stored observation in the hour is used",
    "stable_cost": "amount * cost_bps_taker / 1e4: what the recipient loses against the mid-market rate, in sending-currency units, cheapest stored stablecoin path",
    "stable_cost_pct": "cost_bps_taker / 100: the same loss as a percent of the amount",
    "stable_path": "stored path id: <stable> for the base route, <stable>:<network> for a corridor_variants.csv row; cheapest that hour, ties to base",
    "app_cost": "same loss for the cheapest app: each provider's own quote where stored, else the public comparison panel, then the minimum",
    "app_source": "own or comparison: where the cheapest app's price came from",
    "feed_cost_pct": "samples.csv baseline_cost_bps / 100 (best of the comparison feed), provider in feed_app",
    "stable_cheaper": "stable_cost_pct < app_cost_pct",
    "extra_cost": "stable minus app; negative when the stablecoin path is cheaper",
    "priced_hour": "an hour with both a stablecoin price and an app price; others are omitted",
}


# ---------------------------------------------------------------- helpers

def read_csv(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(row, key):
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def ok(row):
    return (row.get("source_ok") or "").strip() == "True"


def hour_of(ts):
    """'2026-10-05T05:06:10.9+00:00' -> '2026-10-05T05' (UTC hour key)."""
    return (ts or "")[:13]


def hour_utc(key):
    return key + ":00:00Z"


def parse_hour(key):
    return dt.datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=dt.timezone.utc)


def r4(x):
    return None if x is None else round(x, 4)


def percentile(sorted_vals, p):
    """Linear interpolation between closest ranks (p in 0..1)."""
    n = len(sorted_vals)
    if n == 0:
        return None
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def amount_key(v):
    f = float(v)
    return int(f) if f == int(f) else f


# ---------------------------------------------------------------- load

def load():
    """Index every stored series by (route, amount, hour). Later rows in an
    hour overwrite earlier ones (append-only files: file order is time order).
    """
    base, variants, own, panel = {}, {}, {}, {}
    meta = {}
    newest = ""
    for r in read_csv(SAMPLES):
        if not ok(r):
            continue
        ts = r.get("ts") or ""
        c = (r.get("corridor") or "").strip()
        amt = num(r, "notional_src")
        bps = num(r, "cost_bps_taker")
        if not ts or not c or amt is None:
            continue
        newest = max(newest, ts)
        meta.setdefault(c, {"send_ccy": (r.get("src") or "").strip(),
                            "recv_ccy": (r.get("dst") or "").strip()})
        if bps is None:
            continue
        key = (c, amount_key(amt), hour_of(ts))
        base[key] = {
            "ts": ts, "bps": bps, "path": (r.get("stable") or "").strip(),
            "feed_bps": num(r, "baseline_cost_bps"),
            "feed_app": (r.get("baseline_provider") or "").strip() or None,
            "netfee": num(r, "network_fee_stable"),
            "on_basis": num(r, "onramp_basis_bps"),
            "off_basis": num(r, "offramp_basis_bps"),
        }
    for r in read_csv(VARIANTS):
        bps = num(r, "cost_bps_taker")
        if not ok(r) or bps is None or num(r, "notional_src") is None:
            continue
        path = (r.get("stable") or "").strip() + ":" + (r.get("network") or "").strip()
        key = (r["corridor"].strip(), amount_key(num(r, "notional_src")), hour_of(r["ts"]))
        variants.setdefault(key, {})[path] = bps
        newest = max(newest, r["ts"])
    for r in read_csv(QUOTES):
        bps = num(r, "cost_bps")
        if not ok(r) or bps is None or num(r, "size_src") is None or not r.get("provider"):
            continue
        key = (r["corridor"].strip(), amount_key(num(r, "size_src")), hour_of(r["ts_utc"]))
        own.setdefault(key, {})[r["provider"]] = bps
    for c, fname in PANELS.items():
        for r in read_csv(fname):
            bps = num(r, "cost_bps")
            if not ok(r) or bps is None or num(r, "notional_src") is None or not r.get("provider"):
                continue
            key = (c, amount_key(num(r, "notional_src")), hour_of(r["ts_utc"]))
            panel.setdefault(key, {})[r["provider"]] = bps
    legs = {}
    for r in read_csv(WATERFALL):
        key = (r["corridor"].strip(), amount_key(num(r, "notional_src")), hour_of(r["ts"]))
        legs.setdefault(key, {}).update(
            ts=r["ts"], buy=num(r, "wf_buy_bps"), move=num(r, "wf_move_bps"),
            sell=num(r, "wf_sell_bps"))
    for r in read_csv(RAMP_WATERFALL):
        key = (r["corridor"].strip(), amount_key(num(r, "notional_src")), hour_of(r["ts"]))
        legs.setdefault(key, {}).update(
            rts=r["ts"], deposit=num(r, "wf_deposit_bps"),
            withdrawal=num(r, "wf_withdrawal_bps"),
            deposit_measured=(r.get("deposit_measured") or "").strip() == "True",
            withdrawal_measured=(r.get("withdrawal_measured") or "").strip() == "True")
    return {"base": base, "variants": variants, "own": own, "panel": panel,
            "legs": legs, "meta": meta, "newest": newest}


def price_hour(D, c, amt, h):
    """One priced hour, or None. Returns the stable and app sides."""
    key = (c, amt, h)
    paths = {}
    b = D["base"].get(key)
    if b:
        paths[b["path"]] = b["bps"]
    for p, v in (D["variants"].get(key) or {}).items():
        paths[p] = v
    if not paths:
        return None
    # cheapest stored path; ties go to the base route
    best_path = min(paths, key=lambda p: (paths[p], 0 if (b and p == b["path"]) else 1))
    quotes = {}
    for prov, v in (D["panel"].get(key) or {}).items():
        quotes[prov] = (v, "comparison")
    for prov, v in (D["own"].get(key) or {}).items():
        quotes[prov] = (v, "own")                 # own quote wins over panel
    if not quotes:
        return None
    app = min(quotes, key=lambda p: (quotes[p][0], p))
    return {
        "hour": h, "stable_bps": paths[best_path], "stable_path": best_path,
        "base_path": b["path"] if b else None,
        "app_bps": quotes[app][0], "app": app, "app_source": quotes[app][1],
        "feed_bps": b["feed_bps"] if b else None,
        "feed_app": b["feed_app"] if b else None,
    }


def series(D):
    """{route: {amount: [priced-hour dicts sorted by hour]}}"""
    keys = {}
    for store in ("base", "variants"):
        for (c, amt, h) in D[store]:
            keys.setdefault(c, {}).setdefault(amt, set()).add(h)
    out = {}
    for c in ROUTES:
        for amt in sorted(keys.get(c, {})):
            rows = []
            for h in sorted(keys[c][amt]):
                if h < START:
                    continue
                p = price_hour(D, c, amt, h)
                if p:
                    rows.append(p)
            if rows:
                out.setdefault(c, {})[amt] = rows
    return out


# ---------------------------------------------------------------- hourly

HOUR_COLUMNS = [
    "hour_utc", "stable_cost", "stable_cost_pct", "app_cost", "app_cost_pct",
    "cheapest_app", "stable_path", "stable_cheaper", "app_source",
    "feed_cost_pct", "feed_app",
]

def build_hourly(D, S):
    routes = []
    for c in ROUTES:
        if c not in S:
            continue
        amounts = []
        for amt in sorted(S[c]):
            hours = []
            for p in S[c][amt]:
                hours.append([
                    hour_utc(p["hour"]),
                    r4(amt * p["stable_bps"] / 1e4), r4(p["stable_bps"] / 100),
                    r4(amt * p["app_bps"] / 1e4), r4(p["app_bps"] / 100),
                    p["app"], p["stable_path"], p["stable_bps"] < p["app_bps"],
                    p["app_source"],
                    r4(p["feed_bps"] / 100) if p["feed_bps"] is not None else None,
                    p["feed_app"],
                ])
            amounts.append({"amount": amt, "hours": hours})
        m = D["meta"].get(c, {})
        routes.append({"id": c, "send_ccy": m.get("send_ccy"),
                       "recv_ccy": m.get("recv_ccy"), "amounts": amounts})
    return {
        "as_of_utc": D["newest"][:13] and hour_utc(D["newest"][:13]),
        "start": START,
        "definition": DEFINITION,
        "format": "compact: each amount's hours are arrays in the order of hour_columns, to stay under 4 MB",
        "hour_columns": HOUR_COLUMNS,
        "routes": routes,
        "source_files": ["data/" + f for f in
                         [SAMPLES, VARIANTS, QUOTES] + sorted(PANELS.values())],
    }


# ---------------------------------------------------------------- summary

def extras(rows, amt):
    """(extra_units, extra_pp) per hour."""
    return [(amt * (p["stable_bps"] - p["app_bps"]) / 1e4,
             (p["stable_bps"] - p["app_bps"]) / 100) for p in rows]


def window_split(rows):
    """Hours in the last 7 days / the 7 days before, anchored on the series'
    own latest stored hour (no wall clock)."""
    if not rows:
        return [], []
    end = parse_hour(rows[-1]["hour"])
    a = end - dt.timedelta(days=WINDOW_DAYS)
    b = end - dt.timedelta(days=2 * WINDOW_DAYS)
    last, prev = [], []
    for p in rows:
        t = parse_hour(p["hour"])
        if t > a:
            last.append(p)
        elif t > b:
            prev.append(p)
    return last, prev


def stats(rows, amt):
    """Summary block for a list of priced hours. amt None = pooled amounts
    (cost units are not comparable across amounts, so they are null)."""
    n = len(rows)
    if n == 0:
        return None
    wins = sum(1 for p in rows if p["stable_bps"] < p["app_bps"])
    pp = [(p["stable_bps"] - p["app_bps"]) / 100 for p in rows]
    spp = sorted(pp)
    if amt is not None:
        un = [amt * (p["stable_bps"] - p["app_bps"]) / 1e4 for p in rows]
        sun = sorted(un)
    else:
        un = sun = None
    last, prev = window_split(rows)

    def med_pp(rs):
        return st.median((p["stable_bps"] - p["app_bps"]) / 100 for p in rs) if rs else None

    def med_un(rs):
        return (st.median(amt * (p["stable_bps"] - p["app_bps"]) / 1e4 for p in rs)
                if (rs and amt is not None) else None)

    ml, mp = med_pp(last), med_pp(prev)
    ul, up = med_un(last), med_un(prev)
    i_min = min(range(n), key=lambda i: (pp[i], i))
    i_max = max(range(n), key=lambda i: (pp[i], -i))

    def at(i):
        return {"hour_utc": hour_utc(rows[i]["hour"]),
                "gap": r4(un[i]) if un else None, "gap_pp": r4(pp[i])}

    swing_pp = percentile(spp, 0.9) - percentile(spp, 0.1)
    return {
        "hours_priced": n,
        "hours_stable_cheapest": wins,
        "win_rate_pct": round(100 * wins / n, 2),
        "median_extra": r4(st.median(un)) if un else None,
        "median_extra_pp": r4(st.median(pp)),
        "swing": r4(percentile(sun, 0.9) - percentile(sun, 0.1)) if sun else None,
        "swing_pp": r4(swing_pp),
        "change_7d": r4(ul - up) if (ul is not None and up is not None) else None,
        "change_7d_pp": r4(ml - mp) if (ml is not None and mp is not None) else None,
        "change_7d_hours": {"last": len(last), "before": len(prev)},
        "closest_hour": at(i_min),
        "widest_hour": at(i_max),
    }


def build_summary(D, S):
    routes = []
    total_pairs = total_route_hours = 0
    distinct = set()
    for c in ROUTES:
        if c not in S:
            continue
        amounts, per_hour = [], {}
        pooled = []
        for amt in sorted(S[c]):
            rows = S[c][amt]
            amounts.append(dict(amount=amt, **stats(rows, amt)))
            pooled.extend(rows)
            for p in rows:
                per_hour.setdefault(p["hour"], False)
                if p["stable_bps"] < p["app_bps"]:
                    per_hour[p["hour"]] = True
        route_hours = sum(1 for v in per_hour.values() if v)
        pairs = sum(1 for p in pooled if p["stable_bps"] < p["app_bps"])
        total_pairs += pairs
        total_route_hours += route_hours
        distinct.update(h for h, v in per_hour.items() if v)
        # pooled across amounts, percentage points only
        pooled_sorted = sorted(pooled, key=lambda p: p["hour"])
        allst = stats(pooled_sorted, None)
        # the 7-day windows of the pooled set must anchor on the pooled latest
        route_default = DEFAULT_AMOUNT if DEFAULT_AMOUNT in S[c] else None
        # A route is comparable only if the stablecoin cost is not negative at any quoted amount:
        # a negative cost means it is measured against a mid-market rate below the street price,
        # so "cheaper than the app" says nothing about a sender's real saving.
        med_cost = {amt: st.median(p["stable_bps"] for p in S[c][amt]) for amt in S[c]}
        comparable = all(v >= 0 for v in med_cost.values())
        routes.append({
            "id": c,
            "comparable": comparable,
            "comparable_reason": None if comparable else "stable_cost_negative",
            "stable_cost_median_pct_min": r4(min(med_cost.values()) / 100),
            "default_amount": route_default,
            "hours_priced_any_amount": len(per_hour),
            "total_hours_stable_cheapest": route_hours,
            "amount_hours_stable_cheapest": pairs,
            "amounts": amounts,
            "all_amounts": allst,
        })
    return {
        "as_of_utc": D["newest"][:13] and hour_utc(D["newest"][:13]),
        "start": START,
        "windows": {"change_days": WINDOW_DAYS, "swing": "p90 minus p10 of hourly extra cost, linear interpolation"},
        "definition": {
            "comparable": "false when the median stablecoin cost is below zero at any quoted amount: the cost is measured against a mid-market rate below the street price, so the comparison with the app is not like for like",
            "total_hours_stable_cheapest": "route-hours since start in which the stablecoin path was cheaper than the cheapest app at one or more quoted amounts",
            "amount_hours_stable_cheapest": "route-hour-amount observations where the stablecoin path was cheaper",
            "median_extra": "median over priced hours of stable minus app, cost units; negative when stablecoin cheaper",
            "swing": "p90 minus p10 of the hourly extra cost",
            "change_7d": "median extra over the 7 days to the series' latest hour minus median extra over the 7 days before; null if either window has no hour",
            "closest_hour": "the hour with the smallest (most negative) extra cost",
            "widest_hour": "the hour with the largest extra cost",
            "all_amounts": "all quoted amounts pooled; percentage points only, cost units are null because amounts differ",
        },
        "total_hours_stable_cheapest": {
            "route_hours": total_route_hours,
            "distinct_clock_hours": len(distinct),
            "amount_hours": total_pairs,
        },
        "routes": routes,
        "source_files": ["routes_hourly.json"],
    }


# ---------------------------------------------------------------- breakdown

def latest_by(rows, keyf, tsf):
    out = {}
    for r in rows:
        k = keyf(r)
        if k not in out or tsf(r) >= tsf(out[k]):
            out[k] = r
    return out


def fee_schedules():
    ramp = latest_by(read_csv(RAMP_FEES),
                     lambda r: (r["corridor"], r["leg"], r["venue"], r["method"]),
                     lambda r: r["ts_utc"])
    wd = latest_by(read_csv(WITHDRAWAL_FEES),
                   lambda r: (r["venue"], r["asset"], r["network"]),
                   lambda r: r["ts_utc"])
    return {
        "ramp_fees": [{"as_of_utc": r["ts_utc"], "route": r["corridor"], "leg": r["leg"],
                       "venue": r["venue"], "method": r["method"] or None,
                       "currency": r["currency"], "fee_type": r["fee_type"],
                       "fee_value": num(r, "fee_value"), "status": r["status"]}
                      for _, r in sorted(ramp.items())],
        "withdrawal_fees": [{"as_of_utc": r["ts_utc"], "venue": r["venue"],
                             "asset": r["asset"], "network": r["network"],
                             "fee_asset_units": num(r, "fee_asset_units"),
                             "source_ok": ok(r)}
                            for _, r in sorted(wd.items()) if ok(r) or True],
    }


BREAKDOWN_COLUMNS = [
    "hour_utc", "path", "getting_in_deposit", "getting_in_buy", "on_chain",
    "cashing_out_sell", "cashing_out_withdrawal", "total", "total_pct",
    "app_cost", "app_cost_pct", "cheapest_app", "network_fee_stable",
    "onramp_basis_bps", "offramp_basis_bps",
    "deposit_measured", "withdrawal_measured", "legs_as_of_utc",
]


def build_breakdown(D, S):
    routes, gaps = [], []
    for c in ROUTES:
        if c not in S:
            continue
        amounts = []
        first_leg = {"waterfall": None, "ramp": None}
        for amt in sorted(S[c]):
            rows = []
            for p in S[c][amt]:
                key = (c, amt, p["hour"])
                b = D["base"].get(key)
                lg = D["legs"].get(key) or {}
                # legs belong to the base path only: they are the telescoped
                # steps of that path's own cost_bps_taker (collector.py).
                if not b:
                    continue

                def u(x):
                    return None if x is None else r4(amt * x / 1e4)
                have_wf = lg.get("buy") is not None
                have_rw = lg.get("deposit") is not None
                if have_wf and (first_leg["waterfall"] is None or p["hour"] < first_leg["waterfall"]):
                    first_leg["waterfall"] = p["hour"]
                if have_rw and (first_leg["ramp"] is None or p["hour"] < first_leg["ramp"]):
                    first_leg["ramp"] = p["hour"]
                legs_ts = lg.get("ts") or lg.get("rts")
                rows.append([
                    hour_utc(p["hour"]), b["path"],
                    u(lg.get("deposit")), u(lg.get("buy")), u(lg.get("move")),
                    u(lg.get("sell")), u(lg.get("withdrawal")),
                    r4(amt * b["bps"] / 1e4), r4(b["bps"] / 100),
                    r4(amt * p["app_bps"] / 1e4), r4(p["app_bps"] / 100), p["app"],
                    b["netfee"], b["on_basis"], b["off_basis"],
                    lg.get("deposit_measured") if have_rw else None,
                    lg.get("withdrawal_measured") if have_rw else None,
                    hour_utc(hour_of(legs_ts)) if (have_wf or have_rw) else None,
                ])
            amounts.append({"amount": amt, "rows": rows})
        routes.append({"id": c, "amounts": amounts})
        gaps.append({"leg": "getting_in_buy", "route": c, "reason": "stored_from",
                     "first_hour_utc": hour_utc(first_leg["waterfall"]) if first_leg["waterfall"] else None,
                     "cadence": "hourly", "file": "data/" + WATERFALL})
        gaps.append({"leg": "on_chain", "route": c, "reason": "stored_from",
                     "first_hour_utc": hour_utc(first_leg["waterfall"]) if first_leg["waterfall"] else None,
                     "cadence": "hourly", "file": "data/" + WATERFALL})
        gaps.append({"leg": "cashing_out_sell", "route": c, "reason": "stored_from",
                     "first_hour_utc": hour_utc(first_leg["waterfall"]) if first_leg["waterfall"] else None,
                     "cadence": "hourly", "file": "data/" + WATERFALL})
        for leg in ("getting_in_deposit", "cashing_out_withdrawal"):
            gaps.append({"leg": leg, "route": c, "reason": "stored_from",
                         "first_hour_utc": hour_utc(first_leg["ramp"]) if first_leg["ramp"] else None,
                         "cadence": "hourly", "file": "data/" + RAMP_WATERFALL})
    fs = fee_schedules()
    for r in fs["ramp_fees"]:
        if r["status"] != "measured":
            gaps.append({"leg": "getting_in_deposit" if r["leg"] == "deposit" else "cashing_out_withdrawal",
                         "route": r["route"], "reason": "unmeasured_fee",
                         "first_hour_utc": None, "cadence": "snapshot",
                         "as_of_utc": r["as_of_utc"], "file": "data/" + RAMP_FEES})
    gaps.append({"leg": "converting", "route": None, "reason": "not_a_separate_leg",
                 "first_hour_utc": None, "cadence": None,
                 "file": "data/" + SAMPLES,
                 "detail_columns": ["onramp_basis_bps", "offramp_basis_bps"]})
    gaps.append({"leg": "all", "route": None, "reason": "variant_path_total_only",
                 "first_hour_utc": hour_utc("2026-10-02T14"), "cadence": "hourly",
                 "file": "data/" + VARIANTS})
    gaps.append({"leg": "all", "route": None, "reason": "offramp_snapshots_ended",
                 "first_hour_utc": None, "cadence": None,
                 "file": "data/offramp_snapshots.csv"})
    return {
        "as_of_utc": D["newest"][:13] and hour_utc(D["newest"][:13]),
        "unit": "legs, total, app_cost: sending-currency units; total_pct, app_cost_pct: percent of the amount; *_bps: basis points of the amount as stored",
        "definition": {
            "path": "the base route's stablecoin; legs exist only for it",
            "legs": "the five telescoped steps of cost_bps_taker (deposit, buy, on-chain move, sell, withdrawal); they sum to total",
            "getting_in": "deposit + buy", "cashing_out": "sell + withdrawal",
            "on_chain": "network fee leg (move)",
            "null": "not stored for that hour; never carried forward",
            "legs_as_of_utc": "the hour the legs were stored, equal to hour_utc when present",
            "cheapest_app": "same as routes_hourly.json app_cost",
        },
        "columns": BREAKDOWN_COLUMNS,
        "routes": routes,
        "fee_schedules": fs,
        "gaps": gaps,
        "source_files": ["data/" + f for f in
                         [SAMPLES, WATERFALL, RAMP_WATERFALL, RAMP_FEES, WITHDRAWAL_FEES, QUOTES]
                         + sorted(PANELS.values())],
    }


# ---------------------------------------------------------------- what-if

def in_out_bps(lg):
    """(getting in + cashing out) in bps of the amount, or None if any of the
    four stored legs is missing."""
    parts = [lg.get(k) for k in ("deposit", "buy", "sell", "withdrawal")]
    if any(x is None for x in parts):
        return None
    return sum(parts)


def whatif_block(amt, extra_bps, legs_bps, n_hours, hour_info):
    """extra_bps: stable minus app (bps of amount). legs_bps: in+out legs, or None."""
    need_bps = max(0.0, extra_bps)
    out = dict(hour_info)
    out.update({
        "n_hours": n_hours,
        "stable_minus_app": r4(amt * extra_bps / 1e4),
        "stable_minus_app_pp": r4(extra_bps / 100),
        "already_wins": extra_bps < 0 or need_bps == 0,
        "cheaper_needed": r4(amt * need_bps / 1e4),
        "cheaper_needed_pp": r4(need_bps / 100),
        "in_out_legs": r4(amt * legs_bps / 1e4) if legs_bps is not None else None,
        "in_out_legs_pp": r4(legs_bps / 100) if legs_bps is not None else None,
        "cheaper_needed_pct_of_in_out": (r4(100 * need_bps / legs_bps)
                                         if (legs_bps is not None and legs_bps > 0) else None),
    })
    return out


def build_whatif(D, S):
    routes = []
    for c in ROUTES:
        if c not in S:
            continue
        amounts = []
        for amt in sorted(S[c]):
            rows = S[c][amt]
            last = rows[-1]
            lg = D["legs"].get((c, amt, last["hour"])) or {}
            legs_now = (in_out_bps(lg) if last["stable_path"] == last["base_path"] else None)
            latest = whatif_block(
                amt, last["stable_bps"] - last["app_bps"], legs_now, 1,
                {"hour_utc": hour_utc(last["hour"]), "stable_path": last["stable_path"],
                 "base_path": last["base_path"], "cheapest_app": last["app"],
                 "legs_all_measured": (bool(lg.get("deposit_measured")) and bool(lg.get("withdrawal_measured")))
                 if legs_now is not None else None})
            win, _ = window_split(rows)
            med7 = None
            if win:
                ex = st.median(p["stable_bps"] - p["app_bps"] for p in win)
                # the in+out denominator and its matching numerator use only
                # hours whose cheapest path is the base path and whose legs
                # are stored (variant paths store a total, not legs)
                sub = []
                for p in win:
                    if p["stable_path"] != p["base_path"]:
                        continue
                    l = in_out_bps(D["legs"].get((c, amt, p["hour"])) or {})
                    if l is not None:
                        sub.append((p["stable_bps"] - p["app_bps"], l))
                # who was cheapest, so the page can name the app: the one that was cheapest
                # in most of the week's hours (ties: the name that sorts first)
                counts = {}
                for p in win:
                    counts[p["app"]] = counts.get(p["app"], 0) + 1
                top_app = min(counts, key=lambda k: (-counts[k], k))
                med7 = whatif_block(
                    amt, ex, None, len(win),
                    {"from_hour_utc": hour_utc(win[0]["hour"]), "to_hour_utc": hour_utc(win[-1]["hour"]),
                     "cheapest_app_week": top_app, "cheapest_app_week_hours": counts[top_app],
                     "cheapest_app_changed": len(counts) > 1})
                if sub:
                    sex = st.median(a for a, _ in sub)
                    sl = st.median(b for _, b in sub)
                    need = max(0.0, sex)
                    med7["relative_basis"] = {
                        "n_hours": len(sub),
                        "cheaper_needed_pp": r4(need / 100),
                        "in_out_legs_pp": r4(sl / 100),
                        "cheaper_needed_pct_of_in_out": r4(100 * need / sl) if sl > 0 else None,
                        "already_wins": need == 0,
                    }
                else:
                    med7["relative_basis"] = None
            amounts.append({"amount": amt, "latest_hour": latest, "median_7d": med7})
        routes.append({"id": c, "amounts": amounts})
    return {
        "as_of_utc": D["newest"][:13] and hour_utc(D["newest"][:13]),
        "definition": {
            "cheaper_needed": "max(0, stable minus app): how much cheaper getting in plus cashing out must be together for the stablecoin path to match the cheapest app; cost units and percentage points of the amount",
            "already_wins": "stablecoin path is already at or below the cheapest app; cheaper_needed is 0",
            "in_out_legs": "deposit + buy + sell + withdrawal legs of the base path (breakdown file); null when the cheapest path is a variant or a leg is not stored",
            "cheaper_needed_pct_of_in_out": "cheaper_needed as a percent of in_out_legs; null when in_out_legs is null or not above 0",
            "median_7d": "median over the 7 days to the series' latest hour of stable minus app; relative_basis uses only base-path hours with stored legs",
        },
        "routes": routes,
        "source_files": ["routes_hourly.json", "routes_breakdown.json"],
    }


# ---------------------------------------------------------------- io

def dump(path, doc):
    with open(path, "w") as f:
        json.dump(doc, f, separators=(",", ":"), sort_keys=False)
        f.write("\n")


def build_all():
    D = load()
    S = series(D)
    return D, S, {
        "hourly": build_hourly(D, S),
        "summary": build_summary(D, S),
        "breakdown": build_breakdown(D, S),
        "whatif": build_whatif(D, S),
    }


def main():
    D, S, docs = build_all()
    for k, doc in docs.items():
        dump(OUT[k], doc)
        print("wrote %s (%d bytes)" % (os.path.relpath(OUT[k], HERE), os.path.getsize(OUT[k])))
    n = sum(len(a["hours"]) for r in docs["hourly"]["routes"] for a in r["amounts"])
    print("%d routes, %d priced route-amount-hours" % (len(docs["hourly"]["routes"]), n))
    s = docs["summary"]["total_hours_stable_cheapest"]
    print("stablecoin cheapest: %d route-hours, %d distinct hours, %d amount-hours" % (
        s["route_hours"], s["distinct_clock_hours"], s["amount_hours"]))


# ---------------------------------------------------------------- self-test

def _median_indep(vals):
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return None
    m = n // 2
    return v[m] if n % 2 else (v[m - 1] + v[m]) / 2


def self_test():
    fails, notes = [], []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    D, S, docs = build_all()
    # determinism: a second build is byte-identical
    D2, S2, docs2 = build_all()
    for k in docs:
        check(json.dumps(docs[k], sort_keys=False) == json.dumps(docs2[k], sort_keys=False),
              "not idempotent: " + k)
    # on-disk files, if present, must equal a fresh build
    for k, path in OUT.items():
        if os.path.exists(path):
            with open(path) as f:
                check(json.load(f) == json.loads(json.dumps(docs[k])), "stale on disk: " + k)

    # read the emitted hourly JSON back, independent of the build code
    hourly = json.loads(json.dumps(docs["hourly"]))
    ts_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$")
    series_by = {}
    n_hours = 0
    for r in hourly["routes"]:
        check(r["id"] in ROUTES, "unknown route " + r["id"])
        for a in r["amounts"]:
            prev = None
            conv = []
            for row in a["hours"]:
                check(len(row) == len(HOUR_COLUMNS), "row width")
                conv.append(dict(zip(HOUR_COLUMNS, row)))
            a["hours"] = conv
            for h in a["hours"]:
                n_hours += 1
                check(bool(ts_re.match(h["hour_utc"])), "bad hour " + h["hour_utc"])
                try:
                    dt.datetime.strptime(h["hour_utc"], "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    check(False, "unparseable " + h["hour_utc"])
                check(prev is None or h["hour_utc"] > prev, "hours not strictly increasing")
                prev = h["hour_utc"]
                for k in ("stable_cost", "stable_cost_pct", "app_cost", "app_cost_pct"):
                    check(isinstance(h[k], (int, float)), "non-number " + k)
                check(h["stable_cheaper"] == (h["stable_cost_pct"] < h["app_cost_pct"]) or
                      abs(h["stable_cost_pct"] - h["app_cost_pct"]) < 1e-3,
                      "stable_cheaper disagrees with the costs")
                check(abs(h["stable_cost"] - a["amount"] * h["stable_cost_pct"] / 100) < 1e-3 * max(1, a["amount"] / 1000),
                      "stable_cost vs pct")
                check(h["hour_utc"] >= START, "hour before start")
            series_by[(r["id"], a["amount"])] = a["hours"]

    # summary: wins <= hours; medians recomputed from routes_hourly.json
    summary = json.loads(json.dumps(docs["summary"]))
    tot = 0
    for r in summary["routes"]:
        for a in r["amounts"]:
            hrs = series_by[(r["id"], a["amount"])]
            check(a["hours_stable_cheapest"] <= a["hours_priced"], "wins > hours")
            check(a["hours_priced"] == len(hrs), "hours_priced mismatch")
            wins = sum(1 for h in hrs if h["stable_cheaper"])
            check(wins == a["hours_stable_cheapest"], "win count mismatch %s %s" % (r["id"], a["amount"]))
            ex = [h["stable_cost"] - h["app_cost"] for h in hrs]
            exp = [h["stable_cost_pct"] - h["app_cost_pct"] for h in hrs]
            check(abs(_median_indep(ex) - a["median_extra"]) < 2e-3, "median_extra %s %s" % (r["id"], a["amount"]))
            check(abs(_median_indep(exp) - a["median_extra_pp"]) < 2e-3, "median_extra_pp %s %s" % (r["id"], a["amount"]))
            check(a["closest_hour"]["gap_pp"] <= a["median_extra_pp"] + 1e-9 <= a["widest_hour"]["gap_pp"] + 2e-9,
                  "closest/widest bracket the median")
            # 7-day change recomputed
            end = parse_hour(hrs[-1]["hour_utc"][:13])
            def sel(lo, hi):
                return [h["stable_cost_pct"] - h["app_cost_pct"] for h in hrs
                        if end - dt.timedelta(days=lo) < parse_hour(h["hour_utc"][:13]) <= end - dt.timedelta(days=hi)]
            l, p = sel(7, 0), sel(14, 7)
            if l and p:
                check(abs((_median_indep(l) - _median_indep(p)) - a["change_7d_pp"]) < 3e-3, "change_7d_pp")
            else:
                check(a["change_7d_pp"] is None, "change_7d_pp should be null")
        s = r["total_hours_stable_cheapest"]
        any_hours = {}
        for a in r["amounts"]:
            for h in series_by[(r["id"], a["amount"])]:
                any_hours[h["hour_utc"]] = any_hours.get(h["hour_utc"], False) or h["stable_cheaper"]
        check(s == sum(1 for v in any_hours.values() if v), "total_hours_stable_cheapest " + r["id"])
        check(s <= r["hours_priced_any_amount"], "route wins > hours")
        tot += s
    check(summary["total_hours_stable_cheapest"]["route_hours"] == tot, "grand total")

    # what-if: needed cost is never negative, zero iff the path already wins
    for r in docs["whatif"]["routes"]:
        for a in r["amounts"]:
            for blk in (a["latest_hour"], a["median_7d"]):
                if blk is None:
                    continue
                check(blk["cheaper_needed"] >= 0, "negative need")
                check(blk["already_wins"] == (blk["cheaper_needed"] == 0), "already_wins flag")

    # breakdown: legs sum to the stored total where all five legs exist
    bd = docs["breakdown"]
    ci = {c: i for i, c in enumerate(bd["columns"])}
    n_sum = 0
    for r in bd["routes"]:
        for a in r["amounts"]:
            for row in a["rows"]:
                legs = [row[ci[k]] for k in ("getting_in_deposit", "getting_in_buy", "on_chain",
                                             "cashing_out_sell", "cashing_out_withdrawal")]
                if all(x is not None for x in legs):
                    n_sum += 1
                    check(abs(sum(legs) - row[ci["total"]]) <= 0.0006 * max(1, a["amount"] / 100),
                          "legs do not sum %s %s %s" % (r["id"], a["amount"], row[0]))
    notes.append("breakdown rows with all five legs checked: %d" % n_sum)

    # latest hour against what the live site publishes
    pub = json.load(open(os.path.join(DATA, "providers_latest.json")))
    n_stable = n_app = n_stale = 0
    for c, d in pub["corridors"].items():
        crypto_hour = (d.get("crypto_hour_utc") or "")[:13]
        for sz, blk in d["sizes"].items():
            amt = amount_key(sz)
            hrs = series_by.get((c, amt))
            if not hrs or hrs[-1]["hour_utc"][:13] != crypto_hour:
                notes.append("no priced latest hour for %s %s" % (c, sz))
                continue
            mine = hrs[-1]
            D_key = (c, amt, crypto_hour)
            base = D["base"].get(D_key)
            meas = [x for x in blk["rows"] if x["source"] == "measured"]
            if meas and base:
                m = meas[0]
                if m.get("venues"):
                    # published figure is the best exchange pair in the newest
                    # stable_venues.csv snapshot, not this hour's base route
                    if abs(m["cost_pct"] - round(base["bps"] / 100, 4)) > 1e-4:
                        n_stale += 1
                        notes.append("published stablecoin cost for %s %s is the stable_venues.csv pair from %s (%s%%); stored base route this hour %s%%" % (
                            c, sz, m["venues"]["as_of_utc"][:13], m["cost_pct"], round(base["bps"] / 100, 4)))
                else:
                    n_stable += 1
                    check(abs(m["cost_pct"] - round(base["bps"] / 100, 4)) < 1e-4,
                          "stablecoin cost differs from providers_latest %s %s" % (c, sz))
            apps = [x for x in blk["rows"] if x["source"] in ("own", "comparison") and x["cost_pct"] is not None]
            if apps:
                top = min(apps, key=lambda x: x["cost_pct"])
                n_app += 1
                pub_ok = abs(top["cost_pct"] - mine["app_cost_pct"]) < 1e-4
                if not pub_ok:
                    notes.append("cheapest app differs %s %s: published %s %s%%, emitted %s %s%%" % (
                        c, sz, top["provider"], top["cost_pct"], mine["cheapest_app"], mine["app_cost_pct"]))
                check(pub_ok, "cheapest app differs from providers_latest %s %s" % (c, sz))
    notes.append("latest hour: %d stablecoin figures and %d cheapest-app figures equal providers_latest.json; %d published stablecoin figures are from a stale venue snapshot" % (n_stable, n_app, n_stale))

    # corridor_summary.json medians at the 5000 rung vs the emitted series
    cs = json.load(open(os.path.join(DATA, "corridor_summary.json")))
    for row in cs["corridors"]:
        hrs = series_by.get((row["corridor"], DEFAULT_AMOUNT))
        if not hrs:
            continue
        feed = [h["feed_cost_pct"] for h in hrs if h["feed_cost_pct"] is not None]
        notes.append("%s 5000: corridor_summary taker median %.2f bps; emitted-series median %.2f bps; feed median published %.2f vs emitted %.2f" % (
            row["corridor"], row["taker_cost_bps_median"],
            100 * _median_indep([h["stable_cost_pct"] for h in hrs if h["stable_path"] in ("USDT",)]),
            row["baseline_cost_bps_median"], 100 * _median_indep(feed)))
    for n in notes:
        print("  note:", n)
    if fails:
        for f in fails[:40]:
            print("  FAIL:", f)
        print("self-test FAILED (%d)" % len(fails))
        sys.exit(1)
    print("self-test ok: %d priced hours across %d route-amount series" % (n_hours, len(series_by)))


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
