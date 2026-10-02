#!/usr/bin/env python3
"""The receipt behind fee-tiers.html's volume-tier crossover (SEB-192, R2
for the crossover paragraph and tier rows -- same idea SEB-56/SEB-178
already ship for index/country/corridor numbers).

The crossover is not a lookup: `tools/emit_volume_crossover.py` picks a
candidate monthly volume, works out which fee tier that volume unlocks on
each venue, RECONSTRUCTS what this hour's real samples.csv rows would have
cost at that hypothetical fee (reusing their real onramp_vwap/offramp_vwap/
mid_src_dst/network_fee_stable), and binary-searches for the volume where
the typical reconstructed cost first drops below the typical real baseline
cost. This receipt replays that reconstruction in the open: the real rows
it started from, the real fee_tier_schedule.csv rows it applied, the
arithmetic tier_fee_pct()/cost_at_fees() actually ran, and the search that
converged on the published volume.

Reads tools/emit_volume_crossover.py directly for every number it would
otherwise have to retype (LO_VOLUME/HI_VOLUME, tier_fee_pct(), cost_at_fees(),
load_rows(), latest_fx(), median()) so this receipt can never drift from the
calculation it is explaining.

Pinned to data/volume_crossover.json's OWN recorded `tier_schedule_as_of`,
not whatever is newest in data/fee_tier_schedule.csv right now -- the fee
check (tools/check_fees.py) runs on its own monthly cadence and can land a
newer tier table between the two scripts running, and reconstructing against
that newer table would silently explain a different number than the one
published. For the same reason this script is meant to run immediately after
tools/emit_volume_crossover.py, same input files, same moment -- see
BUILDER.md's note on this PR for why data/volume_crossover.json itself is
regenerated alongside this receipt rather than read stale.

Only regimes with status "crosses" get a receipt: fee-tiers.html's own
`#crossoverP` paragraph (and the tier rows under it) only render when both
taker and maker cross, so a status of "never_crosses" or "no_data" has
nothing on the page to attach a receipt to.

Stdlib only. No wall clock. Exits non-zero only if it cannot write.

Usage: python3 tools/emit_crossover_receipts.py
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import emit_volume_crossover as evc  # noqa: E402 -- the calculation this receipt replays

DATA = os.path.join(HERE, "data")
TIER_SCHEDULE = os.path.join(DATA, "fee_tier_schedule.csv")
CROSSOVER = os.path.join(DATA, "volume_crossover.json")
OUT_DIR = os.path.join(DATA, "crossover_receipts")

ITERATIONS = 40  # mirrors the `for _ in range(40)` binary search in
                 # emit_volume_crossover.py's crossover_for_regime()


def hour_of(ts):
    """First 13 characters of an ISO timestamp -- same truncation
    emit_corridor_receipts.py's hour_of() uses, so a receipt filename is
    built the same way everywhere this site writes one."""
    return (ts or "")[:13]


def load_tier_rows_asof(ts_asof):
    """Every data/fee_tier_schedule.csv row stamped exactly `ts_asof` --
    the same moment data/volume_crossover.json recorded as
    `tier_schedule_as_of` -- keyed by (venue, regime), full row detail kept
    (tier_label, volume_ccy, source_url) rather than collapsed to a bare
    (threshold, fee) pair the way emit_volume_crossover.py's own
    load_tier_schedule() does for its internal use.
    """
    if not os.path.exists(TIER_SCHEDULE):
        return {}
    out = {}
    with open(TIER_SCHEDULE, newline="") as f:
        for r in csv.DictReader(f):
            if r["ts_utc"] != ts_asof or r["error"]:
                continue
            out.setdefault((r["venue"], r["regime"]), []).append(r)
    for key in out:
        out[key].sort(key=lambda r: float(r["volume_threshold"]))
    return out


def tier_pairs(rows):
    """(threshold, fee_pct) tuples, the shape evc.tier_fee_pct() reads."""
    return [(float(r["volume_threshold"]), float(r["fee_pct"])) for r in rows]


def load_rows_with_ts():
    """Same rows, same filter, as evc.load_rows() -- but keeping each row's
    own `ts`, which evc.load_rows() drops once it has what its own median
    needs. This receipt names the exact sample each number came from, so it
    needs the timestamp evc.load_rows() throws away.
    """
    rows = [r for r in csv.DictReader(open(evc.SAMPLES))
            if r["corridor"] == evc.CORRIDOR and r["source_ok"] == "True"
            and r.get("notional_src") == evc.RUNG
            and r.get("onramp_filled") == "True"
            and r.get("offramp_filled") == "True"]
    usable = []
    for r in rows:
        notional = evc._float(r, "notional_src")
        on_vwap = evc._float(r, "onramp_vwap")
        off_vwap = evc._float(r, "offramp_vwap")
        mid = evc._float(r, "mid_src_dst")
        netfee = evc._float(r, "network_fee_stable")
        baseline = evc._float(r, "baseline_cost_bps")
        if None in (notional, on_vwap, off_vwap, mid, netfee, baseline):
            continue
        usable.append({
            "ts": r.get("ts"), "notional": notional, "on_vwap": on_vwap, "off_vwap": off_vwap,
            "mid": mid, "netfee": netfee, "baseline": baseline,
            "gross": notional / on_vwap,
        })
    return usable


def reconstruct_row(row, ir_sched, coins_sched, v, fee_on):
    """One real samples.csv row, reconstructed at candidate monthly volume
    `v` -- the exact per-row body of evc.median_cost_at_volume(), pulled out
    here so this receipt can show the per-row arithmetic that function
    normally throws away after taking the median.
    """
    bought_base = row["gross"] * (1 - evc.tier_fee_pct(ir_sched, 0) / 100.0)
    stable_base = bought_base - row["netfee"]
    quote_base = stable_base * row["off_vwap"] if stable_base > 0 else 0.0
    php_vol = quote_base * (v / row["notional"])
    fee_off = evc.tier_fee_pct(coins_sched, php_vol)
    cost = evc.cost_at_fees(row, fee_on, fee_off)
    return {
        "ts": row.get("ts"),
        "onramp_vwap": row["on_vwap"],
        "offramp_vwap": row["off_vwap"],
        "notional_sgd": row["notional"],
        "baseline_cost_bps": row["baseline"],
        "coins_ph_php_volume_at_this_candidate": round(php_vol, 2),
        "fee_off_pct_coins_ph": fee_off,
        "reconstructed_cost_bps": cost,
    }


def build_regime_receipt(regime, doc, rows, ts_asof, tier_rows, fx):
    reg = doc[regime]
    ir_sched = tier_pairs(tier_rows.get(("IndependentReserve", regime), []))
    coins_sched = tier_pairs(tier_rows.get(("Coins.ph", regime), []))
    if not ir_sched or not coins_sched:
        return None  # the fee check hasn't priced this exact tier/regime pair yet -- never guessed

    crossing = reg["monthly_volume_sgd"]
    aud_vol = reg["monthly_volume_aud_on_ir"]
    fee_on = evc.tier_fee_pct(ir_sched, aud_vol)

    recon_rows = [reconstruct_row(r, ir_sched, coins_sched, crossing, fee_on) for r in rows]
    recon_costs = [r["reconstructed_cost_bps"] for r in recon_rows if r["reconstructed_cost_bps"] is not None]
    fee_off_values = [r["fee_off_pct_coins_ph"] for r in recon_rows]
    baseline_med = evc.median([r["baseline"] for r in rows])
    ts_values = [r.get("ts") for r in rows if r.get("ts")]

    return {
        "corridor": doc["corridor"],
        "regime": regime,
        "rung_sgd": doc["rung_sgd"],
        "n_samples": len(rows),
        "baseline_cost_bps_median": baseline_med,
        "evidence": {
            "first_ts": min(ts_values) if ts_values else None,
            "last_ts": max(ts_values) if ts_values else None,
            "rows": [
                {
                    "ts": r["ts"],
                    "onramp_vwap": r["on_vwap"],
                    "offramp_vwap": r["off_vwap"],
                    "baseline_cost_bps": r["baseline"],
                }
                for r in rows
            ],
        },
        "tier_schedule": {
            "tier_schedule_as_of": ts_asof,
            "independent_reserve": {
                "venue": "IndependentReserve",
                "leg": "onramp",
                "regime": regime,
                "rows": [
                    {
                        "tier_label": r["tier_label"],
                        "volume_threshold": float(r["volume_threshold"]),
                        "volume_ccy": r["volume_ccy"],
                        "fee_pct": float(r["fee_pct"]),
                        "source_url": r["source_url"],
                    }
                    for r in tier_rows[("IndependentReserve", regime)]
                ],
            },
            "coins_ph": {
                "venue": "Coins.ph",
                "leg": "offramp",
                "regime": regime,
                "rows": [
                    {
                        "tier_label": r["tier_label"],
                        "volume_threshold": float(r["volume_threshold"]),
                        "volume_ccy": r["volume_ccy"],
                        "fee_pct": float(r["fee_pct"]),
                        "source_url": r["source_url"],
                    }
                    for r in tier_rows[("Coins.ph", regime)]
                ],
            },
        },
        "fx": fx,
        "reconstruction": {
            "crossover_volume_sgd": crossing,
            "crossover_volume_aud_on_ir": aud_vol,
            "fee_pct_at_crossover_ir": fee_on,
            "fee_pct_at_crossover_coins_ph_median": evc.median(fee_off_values),
            "reconstructed_cost_bps_median": evc.median(recon_costs),
            "rows": recon_rows,
        },
        "search": {
            "lo_volume_sgd": evc.LO_VOLUME,
            "hi_volume_sgd": evc.HI_VOLUME,
            "iterations": ITERATIONS,
            "cost_bps_at_floor": reg["cost_bps_at_floor"],
            "cost_bps_at_ceiling": reg["cost_bps_at_ceiling"],
            "converged_volume_sgd": crossing,
        },
        "source_files": [
            "data/samples.csv",
            "data/fee_tier_schedule.csv",
            "data/fx_rates.csv",
            "data/volume_crossover.json",
        ],
    }


def build():
    with open(CROSSOVER) as f:
        doc = json.load(f)
    if doc.get("status") != "ok":
        return {}

    rows = load_rows_with_ts()
    ts_asof = doc["tier_schedule_as_of"]
    tier_rows = load_tier_rows_asof(ts_asof)

    aud_rate, sgd_rate = evc.latest_fx("AUD"), evc.latest_fx("SGD")
    aud_per_sgd = (aud_rate / sgd_rate) if (aud_rate and sgd_rate) else None
    fx = {
        "aud_per_usd": aud_rate,
        "sgd_per_usd": sgd_rate,
        "aud_per_sgd": aud_per_sgd,
        "source_file": "data/fx_rates.csv",
    }

    out = {}
    for regime in ("taker", "maker"):
        reg = doc.get(regime) or {}
        if reg.get("status") != "crosses" or aud_per_sgd is None:
            continue
        receipt = build_regime_receipt(regime, doc, rows, ts_asof, tier_rows, fx)
        if receipt is not None:
            out[f"{regime}_{hour_of(ts_asof)}"] = receipt
    return out


def main():
    receipts = build()
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        for filename, receipt in receipts.items():
            with open(os.path.join(OUT_DIR, f"{filename}.json"), "w") as f:
                json.dump(receipt, f, indent=2, sort_keys=True)
                f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write crossover receipts: {e}", file=sys.stderr)
        sys.exit(1)

    if not receipts:
        print("  wrote 0 crossover receipts -- data/volume_crossover.json has no regime at status \"crosses\" right now")
        return

    for filename, receipt in receipts.items():
        recon = receipt["reconstruction"]
        print(f"  {filename}: reconstructed median {recon['reconstructed_cost_bps_median']} bps "
              f"at S${recon['crossover_volume_sgd']:,.0f}/month "
              f"(published baseline {receipt['baseline_cost_bps_median']} bps)")
    print(f"  wrote {len(receipts)} crossover receipts -> data/crossover_receipts/")


if __name__ == "__main__":
    main()
