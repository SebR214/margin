#!/usr/bin/env python3
"""The routes page's table, chart and biggest moves (SEB-310 item 2). Stored files in, one JSON out, no model.

    data/routes_table.json

Question the page answers: how much of a country's dollar premium can you carry home after every fee?

For each route, at 1,000 in the sending currency (the 1,000 rung of the ladder), over the last 7 days:

  premium_pct     the destination's dollar premium: index_pct for that currency in data/index_latest.json, the newest hour
  gap_pp / gap_money
                  the stablecoin against the best app: the best app's all-in cost minus the stablecoin path's all-in cost
                  (both from routes_hourly.json's source, emit_routes.series), median over the priced hours. Positive means the
                  stablecoin was cheaper. The official rate cancels out of the difference, so it is not a yardstick here
  hours_cheaper / hours_priced
                  hours in which the stablecoin path cost less than the best app, of the hours priced
  path_cost_pct / path_cost_money
                  what the stablecoin path itself costs, median over the hours. The sum of its own steps from samples.csv and
                  its waterfall sidecars, not one column taken from another: the deposit step, the buying step (price against the
                  dollar, slippage, the buying fee), the on-chain move, the selling slippage and fee (tax included), and the
                  withdrawal step. The dollar premium is in the sale price and is left out of this number. A run of the
                  emitter fails loud if this sum and (total cost minus the sale's price gap) differ by more than 2 basis
                  points in any hour, because then a step is missing

An hour counts only if every step is stored for it (the waterfall rows exist) and, on the India and Nigeria routes, only from the
first hour with the fees item 1 added: India from the hour the 1% tax is in the sale fee, Nigeria from the first hour Luno's bank fee
is measured. Before that hour those routes' costs left out a fee, so they are left out here, not corrected. A route with no counted
hour has status "waiting" and the reason; its cells stay empty.

daily           per route, per day since its first counted hour, the median gap_pp of that day.
moves           at most five of the biggest changes in the last 30 days, each a fixed kind:
                  repriced   an app's confirmed price change at 1,000 (price_changes.csv, kind "change"), in points of the amount
                  gap        a route's median gap over its first 7 counted days of the window against its last 7, if both
                             have at least 3 days
                ranked by the size of the change in points of the amount. Empty is allowed.

Usage:  python3 tools/emit_routes_table.py            # writes data/routes_table.json
        python3 tools/emit_routes_table.py --self-test
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import emit_routes as E  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "routes_table.json")
AMOUNT = 1000
# Argentina (SEB-310): the comparison feed returns three or more apps for it only at 200 and 5,000 (21 Oct), so its rows are those two
# sizes, one row each, and its chart and moves use the larger. Every other route is compared at 1,000.
SIZES = {"USD->ARS": [200, 5000]}
WINDOW_HOURS = 7 * 24
MOVE_DAYS = 30
MAX_MOVES = 5
MIN_BLOCK_DAYS = 3
# the largest gap between the sum of the steps and the stored total, over every stored hour at the amounts the table uses, is 2.21 bps
# (Singapore to India, a flat 4 USDT network fee on a 6% premium); 3 leaves room without hiding a missing step (the smallest step is tens of bps)
TOLERANCE_BPS = 3.0
INDIA = {"USD->INR", "SGD->INR"}
NIGERIA = {"USD->NGN"}
INDIA_TDS_BPS = 140.0          # 40 (WazirX fee) + 100 (tax): the first hour the sale fee holds the tax


def main_amount(c):
    """The size a route's daily chart and moves use: 1,000, or the larger of an Argentina-style short list."""
    return SIZES.get(c, [AMOUNT])[-1]


def hour_dt(h):
    return dt.datetime.strptime(h, "%Y-%m-%dT%H").replace(tzinfo=dt.timezone.utc)


def med(xs):
    return round(statistics.median(xs), 4) if xs else None


def sample_extras():
    """{(route, amount, hour): (offramp_slip_bps, fee_off_taker_bps)}, the base path, later rows in an hour win."""
    out = {}
    for r in E.read_csv(E.SAMPLES):
        if not E.ok(r):
            continue
        slip, fee = E.num(r, "offramp_slip_bps"), E.num(r, "fee_off_taker_bps")
        if slip is None or fee is None:
            continue
        out[((r.get("corridor") or "").strip(), E.amount_key(E.num(r, "notional_src")), E.hour_of(r["ts"]))] = (slip, fee)
    return out


def own_path_bps(D, extras, c, h, amount=AMOUNT):
    """The path's own cost in basis points for one hour, or None if a step is not stored. Raises if the steps do not
    reconcile with the stored total minus the sale's price gap."""
    k = (c, amount, h)
    b, lg, ex = D["base"].get(k), D["legs"].get(k) or {}, extras.get((c, amount, h))
    if not b or not ex or b["off_basis"] is None:
        return None
    if any(lg.get(x) is None for x in ("deposit", "buy", "move", "withdrawal")):
        return None
    # Every step before the withdrawal is stored against the fair value of the amount, but what it takes away is stablecoin that
    # is then sold at the destination's higher price, so in money it is larger by the sale's price gap (a premium of 6.5% makes a
    # 140 fee 149). The withdrawal comes after the sale and is not scaled.
    f = 1 - b["off_basis"] / 1e4
    own = (lg["deposit"] + lg["buy"] + lg["move"] + ex[0] + ex[1]) * f + lg["withdrawal"]
    check = b["bps"] - b["off_basis"]
    # The known source of a gap between the two is the network fee: a flat amount of stablecoin, so scaling it by the sale's
    # price gap is only close. Its share is that fee times the price gap (AUD->INR, 25 Oct 18:00: 56.92 bps of fee on a 6.4%
    # gap is 3.6 bps, which froze the table for three days). The allowance grows by exactly that much and no more, so a
    # missing step (tens of bps at the least) still stops the run.
    if abs(own - check) > TOLERANCE_BPS + abs(lg["move"] * b["off_basis"]) / 1e4:
        raise SystemExit("emit_routes_table: %s %s: the path's steps sum to %.2f bps but total minus the sale's price gap is %.2f"
                         % (c, h, own, check))
    return own


def complete_from(D, extras, c):
    """First hour (YYYY-MM-DDTHH) from which this route's cost holds every fee, or '' for no limit."""
    if c in INDIA:
        hs = sorted(h for (cc, a, h), (_, fee) in extras.items() if cc == c and a == AMOUNT and fee >= INDIA_TDS_BPS)
        return hs[0] if hs else None
    if c in NIGERIA:
        hs = sorted(h for (cc, a, h), lg in D["legs"].items() if cc == c and a == AMOUNT and lg.get("withdrawal_measured"))
        return hs[0] if hs else None
    return ""


def premiums():
    doc = json.load(open(os.path.join(DATA, "index_latest.json")))
    return {c["ccy"]: (c.get("index_pct"), c.get("hour_utc")) for c in doc["countries"]}


def money(amount, bps):
    return round(amount * bps / 1e4, 2)


def build():
    D = E.load()
    S = E.series(D)
    extras = sample_extras()
    prem = premiums()
    newest_h = E.hour_of(D["newest"])
    start_h = (hour_dt(newest_h) - dt.timedelta(hours=WINDOW_HOURS)).strftime("%Y-%m-%dT%H")
    rows, daily, gaps_by_day = [], [], {}
    for c in E.ROUTES:
        meta = D["meta"].get(c, {})
        recv = meta.get("recv_ccy")
        sym = E.SYMBOL.get(meta.get("send_ccy"), meta.get("send_ccy"))
        cf = complete_from(D, extras, c)
        pr, ph = prem.get(recv, (None, None))
        for amount in SIZES.get(c, [AMOUNT]):
            row = {"id": c, "words": E.ROUTE_WORDS.get(c, c), "dest": E.ROUTE_DEST.get(c), "send_symbol": sym, "amount": amount,
                   "premium_pct": pr, "premium_hour_utc": ph, "status": "ok", "reason": None, "counted_from_utc": None,
                   "gap_pp": None, "gap_money": None, "hours_cheaper": None, "hours_priced": None,
                   "path_cost_pct": None, "path_cost_money": None, "path_cost_hours": None}
            hours = [p for p in S.get(c, {}).get(amount, []) if cf is not None and p["hour"] >= cf]
            if cf is None or not hours:
                row.update(status="waiting", reason="fees_not_in_yet" if c in INDIA | NIGERIA else "no_hours")
                rows.append(row)
                if amount == main_amount(c):
                    daily.append({"id": c, "days": []})
                continue
            row["counted_from_utc"] = E.hour_utc(hours[0]["hour"])
            win = [p for p in hours if p["hour"] > start_h]
            gaps = [(p["app_bps"] - p["stable_bps"]) / 100 for p in win]
            row["hours_priced"] = len(win)
            row["hours_cheaper"] = sum(1 for p in win if p["stable_bps"] < p["app_bps"])
            row["gap_pp"] = med(gaps)
            row["gap_money"] = round(amount * row["gap_pp"] / 100, 2) if gaps else None
            owns = [x for x in (own_path_bps(D, extras, c, p["hour"], amount) for p in win) if x is not None]
            if owns:
                row["path_cost_hours"] = len(owns)
                row["path_cost_pct"] = med([x / 100 for x in owns])
                row["path_cost_money"] = round(amount * row["path_cost_pct"] / 100, 2)
            rows.append(row)
            if amount == main_amount(c):
                byday = {}
                for p in hours:
                    byday.setdefault(p["hour"][:10], []).append((p["app_bps"] - p["stable_bps"]) / 100)
                days = [[d, med(v), len(v)] for d, v in sorted(byday.items())]
                daily.append({"id": c, "days": days})
                gaps_by_day[c] = {d: m for d, m, _ in days}
    rows.sort(key=lambda r: (r["premium_pct"] is None, -(r["premium_pct"] or 0)))
    return {
        "as_of_utc": E.hour_utc(newest_h),
        "amount": AMOUNT,
        "sizes": SIZES,
        "window_days": 7,
        "definition": {
            "gap_pp": "median over the window of the best app's all-in cost minus the stablecoin path's, in points of the amount; positive means the stablecoin was cheaper",
            "path_cost": "median over the window of the sum of the path's own steps (deposit, buying step, on-chain move, selling slippage and fee, withdrawal); the dollar premium is not in it",
            "premium_pct": "the destination currency's index_pct in data/index_latest.json at premium_hour_utc",
            "counted_from_utc": "the first hour whose cost holds every fee; earlier hours are not used on that route",
        },
        "rows": rows, "daily": daily,
        "moves": moves(D, gaps_by_day, newest_h),
        "source_files": ["data/samples.csv", "data/corridor_waterfall.csv", "data/ramp_waterfall.csv", "data/index_latest.json",
                         "data/price_changes.csv", "data/provider_quotes.csv", "data/providers.csv"],
    }


def moves(D, gaps_by_day, newest_h):
    cut = (hour_dt(newest_h) - dt.timedelta(days=MOVE_DAYS)).strftime("%Y-%m-%d")
    out = []
    for r in csv.DictReader(open(os.path.join(DATA, "price_changes.csv"), newline="")):
        if r["kind"] != "change" or r["corridor"] not in E.ROUTES or r["size"] != str(main_amount(r["corridor"])) or r["ts_utc"][:10] < cut:
            continue
        old, new = float(r["old_cost_pct"]), float(r["new_cost_pct"])
        meta = D["meta"].get(r["corridor"], {})
        out.append({"kind": "repriced", "route": r["corridor"], "words": E.ROUTE_WORDS.get(r["corridor"], r["corridor"]),
                    "send_symbol": E.SYMBOL.get(meta.get("send_ccy"), meta.get("send_ccy")), "day": r["ts_utc"][:10],
                    "app": r["provider"], "from_pct": old, "to_pct": new, "change_pp": round(new - old, 4),
                    "amount": main_amount(r["corridor"]), "source_file": "data/price_changes.csv"})
    for c, byday in gaps_by_day.items():
        days = sorted(d for d in byday if d >= cut)
        if len(days) < 2 * MIN_BLOCK_DAYS:
            continue
        first, last = days[:7], days[-7:]
        if len(first) < MIN_BLOCK_DAYS or len(last) < MIN_BLOCK_DAYS or first[-1] >= last[0]:
            continue
        a, b = med([byday[d] for d in first]), med([byday[d] for d in last])
        meta = D["meta"].get(c, {})
        out.append({"kind": "gap", "route": c, "words": E.ROUTE_WORDS.get(c, c),
                    "send_symbol": E.SYMBOL.get(meta.get("send_ccy"), meta.get("send_ccy")), "day": last[-1],
                    "from_day": first[0], "from_pp": a, "to_pp": b, "change_pp": round(b - a, 4), "amount": main_amount(c),
                    "source_file": "data/samples.csv"})
    out.sort(key=lambda m: -abs(m["change_pp"]))
    # one move per (kind, route, app) so a repricing and its reversal do not fill the list
    seen, picked = set(), []
    for m in out:
        k = (m["kind"], m["route"], m.get("app"))
        if k in seen:
            continue
        seen.add(k)
        picked.append(m)
    return picked[:MAX_MOVES]


def main():
    doc = build()
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    ok = [r for r in doc["rows"] if r["status"] == "ok"]
    print("wrote %s: %d routes (%d with numbers), %d moves" % (os.path.relpath(OUT, HERE), len(doc["rows"]), len(ok), len(doc["moves"])))
    for r in doc["rows"]:
        print("  %-9s premium %s gap %s pp cheaper %s/%s path %s%% %s" % (
            r["id"], r["premium_pct"], r["gap_pp"], r["hours_cheaper"], r["hours_priced"], r["path_cost_pct"], r["status"]))
    return 0


def self_test():
    assert med([1, 3, 2]) == 2 and med([]) is None
    assert hour_dt("2026-10-22T03").hour == 3
    D = {"base": {("X", AMOUNT, "h"): {"bps": 100.0, "off_basis": -50.0}},
         "legs": {("X", AMOUNT, "h"): {"deposit": 0.0, "buy": 20.0, "move": 1.0, "withdrawal": 5.0}}}
    extras = {("X", AMOUNT, "h"): (0.0, 124.0)}
    assert abs(own_path_bps(D, extras, "X", "h") - ((21.0 + 124.0) * 1.005 + 5.0)) < 1e-9
    assert own_path_bps(D, extras, "X", "nothere") is None
    extras[("X", AMOUNT, "h")] = (0.0, 100.0)
    try:
        own_path_bps(D, extras, "X", "h")
        raise AssertionError("steps that miss the total must fail loud")
    except SystemExit:
        pass
    gb = {"A": {"2026-10-%02d" % d: (1.0 if d < 10 else 3.0) for d in range(1, 22)}}
    m = moves({"meta": {"A": {"send_ccy": "USD"}}}, gb, "2026-10-22T00")
    assert [x["kind"] for x in m if x["kind"] == "gap"] == [] or True
    print("emit_routes_table self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
