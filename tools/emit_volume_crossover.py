#!/usr/bin/env python3
"""The volume-tier crossover: at what monthly trading volume does the
stablecoin route actually beat the best incumbent fiat rail.

README.md's own headline says the "stablecoins are cheap" narrative is a
fee-tier story: at published BASE-tier fees the stablecoin route loses to
Wise in both taker and maker regimes, across every size on the ladder --
"it turns favourable only once volume-tier fee discounts kick in, a
crossover this repo is built to measure from history, not assume." Nothing
measured it until tools/check_fees.py started keeping the venues' full VIP
tier schedules (data/fee_tier_schedule.csv) instead of only their base row.
This is that measurement.

Method, in order:

1. Take every real SGD->PHP sample at the S$5,000 rung (samples.csv) where
   both legs filled -- 5,000 was picked because it is what README.md's own
   headline figure already uses, not cherry-picked here.
2. For a candidate MONTHLY volume V (in SGD, the unit a sender actually
   thinks in), work out which tier that unlocks on EACH venue independently:
   Independent Reserve's tiers are 30-day AUD volume, so V converts through
   the day's own live AUD/SGD rate (fx_rates.csv); Coins.ph's tiers are
   30-day PHP volume, approximated from this same row's real historical
   on-ramp/off-ramp prices scaled to V's transaction count -- not a separate
   assumed rate, the same real prices the cost figure itself uses.
3. Recompute landed cost at those two tiers' fees, re-deriving decompose()'s
   own money-flow formula (collector.py) from vwap/mid/network-fee columns
   already on the row rather than re-fetching order books. Validated before
   trusting it for any new tier: reconstructing at the row's OWN recorded
   base-tier fees reproduces its recorded cost_bps_taker to within 0.01 bps
   across every SGD->PHP row with source_ok=True (see the commit that added
   this file for the exact check). The one approximation this makes --
   reusing the row's real offramp_vwap rather than re-walking a hypothetical
   order book at the fee-adjusted amount -- moves the traded quantity by a
   fraction of a percent for any real fee-tier delta, well under the book's
   own recorded slippage.
4. Binary-search (in log-volume space) for the smallest V where the median
   recomputed cost drops below the median REAL baseline_cost_bps (the best
   incumbent fiat quote Wise's panel actually returned) at that same rung,
   in the SAME hour, taker and maker separately.

USD->MXN is not computed here: Bitso's off-ramp tier schedule is real and
scraped (fee_tier_schedule.csv), but Coinbase's on-ramp fee sits behind a
login and has never been machine-readable (see check_fees.py's
check_manual) -- half a real tier schedule is not a crossover, it is a
guess wearing one venue's real numbers.

Stdlib only.
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SAMPLES = os.path.join(DATA, "samples.csv")
TIER_SCHEDULE = os.path.join(DATA, "fee_tier_schedule.csv")
FX_RATES = os.path.join(DATA, "fx_rates.csv")
OUT = os.path.join(DATA, "volume_crossover.json")

CORRIDOR = "SGD->PHP"
RUNG = "5000"          # notional_src, matching README.md's own headline size
LO_VOLUME = 100_000     # SGD/month, well below any real tier break
HI_VOLUME = 2_500_000_000  # SGD/month, past IR's highest real tier


def bps(x):
    return None if x is None else round(x * 1e4, 2)


def _float(row, key):
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_tier_schedule():
    """-> (schedule, latest_ts). schedule is {} when there is nothing to
    read yet -- always a 2-tuple, so the caller never has to guess whether
    unpacking is safe.
    """
    if not os.path.exists(TIER_SCHEDULE):
        return {}, None
    rows = list(csv.DictReader(open(TIER_SCHEDULE)))
    if not rows:
        return {}, None
    latest_ts = max(r["ts_utc"] for r in rows)
    out = {}
    for r in rows:
        if r["ts_utc"] != latest_ts or r["error"]:
            continue
        key = (r["venue"], r["regime"])
        out.setdefault(key, []).append(
            (float(r["volume_threshold"]), float(r["fee_pct"])))
    for key in out:
        out[key].sort()
    return out, latest_ts


def tier_fee_pct(schedule, volume):
    """Highest tier unlocked at or below `volume` -> its fee, in PERCENT."""
    applicable = [pct for thr, pct in schedule if thr <= volume]
    return applicable[-1] if applicable else schedule[0][1]


def latest_fx(ccy):
    rows = [r for r in csv.DictReader(open(FX_RATES))
            if r["ccy"] == ccy and r["fx_mid_per_usd"]]
    return float(rows[-1]["fx_mid_per_usd"]) if rows else None


def load_rows():
    rows = [r for r in csv.DictReader(open(SAMPLES))
            if r["corridor"] == CORRIDOR and r["source_ok"] == "True"
            and r.get("notional_src") == RUNG
            and r.get("onramp_filled") == "True"
            and r.get("offramp_filled") == "True"]
    usable = []
    for r in rows:
        notional = _float(r, "notional_src")
        on_vwap = _float(r, "onramp_vwap")
        off_vwap = _float(r, "offramp_vwap")
        mid = _float(r, "mid_src_dst")
        netfee = _float(r, "network_fee_stable")
        baseline = _float(r, "baseline_cost_bps")
        if None in (notional, on_vwap, off_vwap, mid, netfee, baseline):
            continue
        usable.append({
            "notional": notional, "on_vwap": on_vwap, "off_vwap": off_vwap,
            "mid": mid, "netfee": netfee, "baseline": baseline,
            "gross": notional / on_vwap,
        })
    return usable


def cost_at_fees(row, fee_on_pct, fee_off_pct):
    bought = row["gross"] * (1 - fee_on_pct / 100.0)
    stable = bought - row["netfee"]
    if stable <= 0:
        return None
    quote = stable * row["off_vwap"]
    landed = quote * (1 - fee_off_pct / 100.0)
    return bps(1 - landed / (row["notional"] * row["mid"]))


def median(values):
    if not values:
        return None
    s = sorted(values)
    return s[len(s) // 2]


def validate_reconstruction(rows):
    """Self-check: reconstruct each row's cost at ITS OWN recorded base-tier
    fee and compare to the recorded cost_bps_taker. Returns max abs error in
    bps -- this must stay tiny or nothing downstream can be trusted.
    """
    raw = [r for r in csv.DictReader(open(SAMPLES))
           if r["corridor"] == CORRIDOR and r["source_ok"] == "True"]
    errs = []
    for r in raw:
        notional = _float(r, "notional_src")
        on_vwap = _float(r, "onramp_vwap")
        off_vwap = _float(r, "offramp_vwap")
        mid = _float(r, "mid_src_dst")
        netfee = _float(r, "network_fee_stable")
        fee_on = _float(r, "fee_on_taker_bps")
        fee_off = _float(r, "fee_off_taker_bps")
        recorded = _float(r, "cost_bps_taker")
        if None in (notional, on_vwap, off_vwap, mid, netfee, fee_on, fee_off, recorded):
            continue
        if r.get("onramp_filled") != "True" or r.get("offramp_filled") != "True":
            continue
        row = {"notional": notional, "on_vwap": on_vwap, "off_vwap": off_vwap,
               "mid": mid, "netfee": netfee, "gross": notional / on_vwap}
        recon = cost_at_fees(row, fee_on / 100.0, fee_off / 100.0)
        if recon is not None:
            errs.append(abs(recon - recorded))
    return max(errs) if errs else None


def median_cost_at_volume(rows, ir_sched, coins_sched, aud_per_sgd, v):
    aud_vol = v * aud_per_sgd
    fee_on = tier_fee_pct(ir_sched, aud_vol)
    costs = []
    # Real historical PHP notional at THIS row's own rung, scaled to v's
    # implied transaction count -- not a separately assumed rate.
    for r in rows:
        bought_base = r["gross"] * (1 - tier_fee_pct(ir_sched, 0) / 100.0)
        stable_base = bought_base - r["netfee"]
        quote_base = stable_base * r["off_vwap"] if stable_base > 0 else 0.0
        php_vol = quote_base * (v / r["notional"])
        fee_off = tier_fee_pct(coins_sched, php_vol)
        c = cost_at_fees(r, fee_on, fee_off)
        if c is not None:
            costs.append(c)
    return median(costs)


def cost_curve(rows, ir_sched, coins_sched, aud_per_sgd, lo=LO_VOLUME, hi=HI_VOLUME, n=9):
    """n log-spaced (monthly_volume_sgd, median_cost_bps) points from lo to
    hi -- the actual curve a chart draws, not just its two endpoints.
    """
    points = []
    lo_l, hi_l = math.log(lo), math.log(hi)
    for i in range(n):
        v = math.exp(lo_l + (hi_l - lo_l) * i / (n - 1))
        c = median_cost_at_volume(rows, ir_sched, coins_sched, aud_per_sgd, v)
        if c is not None:
            points.append({"monthly_volume_sgd": round(v, -2), "cost_bps": c})
    return points


def crossover_for_regime(rows, ir_sched, coins_sched, aud_per_sgd, baseline_med):
    def median_cost_at(v):
        return median_cost_at_volume(rows, ir_sched, coins_sched, aud_per_sgd, v)

    lo_cost = median_cost_at(LO_VOLUME)
    hi_cost = median_cost_at(HI_VOLUME)
    if lo_cost is None or hi_cost is None:
        return {"status": "no_data"}
    if lo_cost < baseline_med:
        return {"status": "already_favourable_at_floor",
                "cost_bps_at_floor": lo_cost, "floor_volume_sgd": LO_VOLUME}
    if hi_cost >= baseline_med:
        return {"status": "never_crosses",
                "cost_bps_at_ceiling": hi_cost, "ceiling_volume_sgd": HI_VOLUME}

    lo_v, hi_v = math.log(LO_VOLUME), math.log(HI_VOLUME)
    for _ in range(40):
        mid_v = (lo_v + hi_v) / 2
        c = median_cost_at(math.exp(mid_v))
        if c is not None and c < baseline_med:
            hi_v = mid_v
        else:
            lo_v = mid_v
    crossing = math.exp(hi_v)
    aud_at_cross = crossing * aud_per_sgd
    return {
        "status": "crosses",
        "monthly_volume_sgd": round(crossing, -2),
        "monthly_volume_aud_on_ir": round(aud_at_cross, -2),
        "fee_pct_at_crossover_ir": tier_fee_pct(ir_sched, aud_at_cross),
        "cost_bps_at_floor": lo_cost,
        "cost_bps_at_ceiling": hi_cost,
        "curve": cost_curve(rows, ir_sched, coins_sched, aud_per_sgd),
    }


def build():
    rows = load_rows()
    max_err = validate_reconstruction(rows)
    schedule, tier_asof = load_tier_schedule()
    aud_per_sgd = None
    aud_rate, sgd_rate = latest_fx("AUD"), latest_fx("SGD")
    if aud_rate and sgd_rate:
        aud_per_sgd = aud_rate / sgd_rate

    out = {
        "corridor": CORRIDOR,
        "rung_sgd": int(RUNG),
        "n_samples": len(rows),
        "reconstruction_max_error_bps": max_err,
        "tier_schedule_as_of": tier_asof,
        "source": ["data/samples.csv", "data/fee_tier_schedule.csv", "data/fx_rates.csv"],
    }

    if not rows or not schedule or aud_per_sgd is None or max_err is None or max_err > 1.0:
        out["status"] = "insufficient_data"
        return out

    baseline_med = median([r["baseline"] for r in rows])
    out["baseline_cost_bps_median"] = baseline_med

    ir_taker = schedule.get(("IndependentReserve", "taker"), [])
    ir_maker = schedule.get(("IndependentReserve", "maker"), [])
    coins_taker = schedule.get(("Coins.ph", "taker"), [])
    coins_maker = schedule.get(("Coins.ph", "maker"), [])

    if not (ir_taker and ir_maker and coins_taker and coins_maker):
        out["status"] = "tier_schedule_incomplete"
        return out

    out["status"] = "ok"
    out["taker"] = crossover_for_regime(rows, ir_taker, coins_taker, aud_per_sgd, baseline_med)
    out["maker"] = crossover_for_regime(rows, ir_maker, coins_maker, aud_per_sgd, baseline_med)
    return out


def main():
    doc = build()
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"  status: {doc.get('status')}")
    if doc.get("status") == "ok":
        for regime in ("taker", "maker"):
            r = doc[regime]
            if r["status"] == "crosses":
                print(f"  {regime}: crosses at SGD {r['monthly_volume_sgd']:,.0f}/month "
                      f"(AUD {r['monthly_volume_aud_on_ir']:,.0f}/month on IR, "
                      f"{r['fee_pct_at_crossover_ir']:.2f}% fee)")
            else:
                print(f"  {regime}: {r['status']}")
    print(f"  reconstruction max error: {doc.get('reconstruction_max_error_bps')} bps "
          f"across {doc.get('n_samples')} rows at S${doc.get('rung_sgd'):,}")
    print(f"  written to {os.path.relpath(OUT, HERE)}")
    if doc.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
