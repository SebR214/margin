#!/usr/bin/env python3
"""The receipt behind a corridor's cost-in-bps figure (SEB-178, R2 for
corridor.html): data/corridor_receipts/<corridor>_<notional>_<hour>.json.

Same idea as tools/emit_receipts.py (SEB-56/R2 for index/country numbers):
nothing here is measured fresh. This re-opens files the collector and the
waterfall sidecars already wrote and shows their rows next to the cost
figure they produced, so js/receipt_replay.js's four-step overlay can
replay a corridor's cost the same way it already replays an index number.

Everything comes from data already on disk:
  data/samples.csv            one row per ladder rung per corridor per
                               hour (collector.py's decompose()) -- the
                               order-book evidence and both regimes'
                               cost_bps_taker / cost_bps_maker.
  data/corridor_waterfall.csv the taker-regime buy/move/sell legs, keyed
                               by ts+corridor+notional_src.
  data/ramp_waterfall.csv     the taker-regime deposit/withdrawal legs,
                               same join key -- a separate sidecar because
                               corridor_waterfall.csv's header is frozen.
  collector.py's CORRIDORS    the fee constants themselves (bps, venue,
                               the date each was last verified), imported
                               straight from the module that owns them
                               rather than retyped here.

Scope cut, found while checking this is buildable (see the issue): the raw
order-book levels the VWAP walk actually consumed are never persisted --
collector.py holds them in memory for one run and discards them. This
receipt shows the fee arithmetic in full -- every leg, every constant,
every source file -- but says plainly that the book itself was not kept,
rather than showing or implying a level it does not have.

Only the taker regime ("market order", the "Stablecoin" ladder column) has
a leg-by-leg breakdown: decompose() only walks deposit -> buy -> move ->
sell -> withdraw for that regime (corridor.html's own waterfall chart only
ever draws the taker breakdown too). A maker-regime ("limit order") receipt
still carries its own real total (cost_bps_maker) and the same fee
constants, it just has no step-by-step legs to list -- said plainly, never
filled in with the taker legs under a different number.

One receipt per (corridor, notional) pair, for the latest hour that pair
has a source_ok row -- the same "rebuild from the latest known state" rule
emit_receipts.py follows for data/countries/<CCY>.json. A new hour's sample
makes a new file (the previous hour's file is left alone, since its own
filename already carries that hour); corridor.html always displays the
latest hour, so it only ever asks for the file this run just wrote.

Stdlib only. No wall clock: every value here is read from a row the
collector already timestamped. Exits non-zero only if it cannot write.

Usage: python3 tools/emit_corridor_receipts.py
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import collector  # noqa: E402 -- CORRIDORS, the fee constants this receipt cites

DATA = os.path.join(HERE, "data")
SAMPLES = os.path.join(DATA, "samples.csv")
CORRIDOR_WATERFALL = os.path.join(DATA, "corridor_waterfall.csv")
RAMP_WATERFALL = os.path.join(DATA, "ramp_waterfall.csv")
OUT_DIR = os.path.join(DATA, "corridor_receipts")

# Mirrors corridor.html's own VENUE map -- cosmetic display names only, the
# same small presentational duplication chart.js already carries for
# chart.py's geometry. A venue not listed falls back to its raw id with
# underscores turned to spaces, same rule the JS side uses.
VENUE_DISPLAY = {
    "IndependentReserve": "Independent Reserve",
    "Coins.ph": "Coins.ph",
    "Coins_ph": "Coins.ph",
    "OKX_P2P": "OKX P2P",
    "Bitso": "Bitso",
    "Binance_P2P": "Binance P2P",
}


def venue_display(v):
    return VENUE_DISPLAY.get(v, (v or "").replace("_", " "))


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num(row, key):
    if row is None:
        return None
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v == v else None


def flag(row, key):
    return (row.get(key) or "").strip() == "True"


def corridor_slug(corridor):
    return corridor.replace("->", "-")


def hour_of(ts):
    """First 13 characters of an ISO timestamp -- "2026-08-10T09" -- the
    same truncation corridor.html's own JS already uses to bucket samples
    into hours (`r.ts.slice(0,13)`). Matched exactly so the page can build
    the same filename this script writes, without parsing a date."""
    return (ts or "")[:13]


def latest_rows_by_key(sample_rows):
    """The newest source_ok row for each (corridor, notional_src) pair --
    the same selection corridor.html's own selectCorridor()/bySize makes."""
    best = {}
    for r in sample_rows:
        if r.get("source_ok") != "True":
            continue
        key = (r.get("corridor"), r.get("notional_src"))
        if key not in best or r.get("ts", "") > best[key].get("ts", ""):
            best[key] = r
    return best


def index_waterfall(path):
    """ts+corridor+notional_src -> row, the same join key corridor.html's
    own JS uses for this exact sidecar."""
    out = {}
    for r in rows(path):
        out[(r.get("ts"), r.get("corridor"), r.get("notional_src"))] = r
    return out


def ramp_leg(direction, src_or_dst, leg_cfg, ramp_row, measured_col, venue_for_note):
    """One deposit/withdrawal leg, tri-state exactly like corridor.html's
    own depositMeasured/withdrawalMeasured: priced (checked, free right
    now), not_priced (checked, no free method published -- CORRIDORS'
    fee_type "gap"), or not_modeled (this corridor's CORRIDORS entry has no
    deposit/withdrawal key at all yet -- USD->NGN, USD->INR, SGD->INR as of
    this writing). A missing ramp_waterfall.csv row (the brief window right
    after this sidecar first shipped for a sample) is its own fourth state,
    not_available, read from the row's own absence rather than guessed.
    """
    if ramp_row is None:
        status = "not_available"
    elif leg_cfg is None:
        status = "not_modeled"
    elif (ramp_row.get(measured_col) or "").strip() == "False":
        status = "not_priced"
    else:
        status = "priced"

    value_bps = num(ramp_row, "wf_" + direction + "_bps") if ramp_row else None
    # Falls back to the matching on-ramp/off-ramp exchange's own venue when
    # CORRIDORS has no dedicated deposit/withdrawal entry (not_modeled) --
    # a real fact (that exchange is where the money would land), not a
    # guess, and the only way the deposit leg's own label ever names a
    # venue for those corridors.
    venue = (leg_cfg.get("venue") if leg_cfg else None) or venue_for_note
    # Same phrasing corridor.html's own waterfall card already uses --
    # "Get {src} onto {venue}" for the deposit leg, "Get {dst} into a bank
    # account" for the withdrawal leg, with no venue named on that side
    # (the destination is a bank, not the exchange).
    leg_phrase = (f"getting {src_or_dst} onto {venue_display(venue)}" if direction == "deposit"
                  else f"getting {src_or_dst} into a bank account")
    meaning = {
        "priced": f"The bank fee for {leg_phrase}. Checked this hour and currently free.",
        "not_priced": f"The bank fee for {leg_phrase}. Checked: no free method at this size is published, so "
                      "this leg is charged nothing here rather than a guess, but it is not actually free.",
        "not_modeled": f"The bank fee for {leg_phrase} has not been priced for this corridor yet.",
        "not_available": f"Not available for this particular sample yet -- the sidecar that prices this leg "
                          "started after this sample was collected.",
    }[status]

    return {
        "status": status,
        "value_bps": value_bps,
        "value_bps_meaning": "This leg's share of the total cost, in hundredths of a percent of the amount sent. "
                              "Zero means either genuinely free or not priced -- see status.",
        "venue": venue,
        "venue_display": venue_display(venue) if venue else None,
        "method": (leg_cfg or {}).get("method"),
        "source_url": (leg_cfg or {}).get("source_url"),
        "verified": (leg_cfg or {}).get("verified"),
        "meaning": meaning,
    }


def build_receipt(corridor, notional_src, row, wf_row, ramp_row, cfg):
    src, dst = row.get("src"), row.get("dst")
    onramp_venue, offramp_venue = row.get("onramp_venue"), row.get("offramp_venue")
    on_cfg, off_cfg = cfg.get("onramp", {}), cfg.get("offramp", {})

    evidence = {
        "onramp": {
            "venue": onramp_venue,
            "venue_display": venue_display(onramp_venue),
            "top_price": num(row, "onramp_top_ask"),
            "top_price_meaning": "The best price on offer to buy the stablecoin when this hour's sample was taken.",
            "average_price_paid": num(row, "onramp_vwap"),
            "average_price_paid_meaning": "The real average price paid after buying through the order book at this "
                                           "amount, walking down from the best price.",
            "slippage_bps": num(row, "onramp_slip_bps"),
            "slippage_bps_meaning": "How much worse the average price paid was than the best price on offer, in "
                                    "hundredths of a percent.",
            "filled": flag(row, "onramp_filled"),
        },
        "offramp": {
            "venue": offramp_venue,
            "venue_display": venue_display(offramp_venue),
            "top_price": num(row, "offramp_top_bid"),
            "top_price_meaning": "The best price on offer to sell the stablecoin when this hour's sample was taken.",
            "average_price_received": num(row, "offramp_vwap"),
            "average_price_received_meaning": "The real average price received after selling through the order "
                                               "book at this amount, walking down from the best price.",
            "slippage_bps": num(row, "offramp_slip_bps"),
            "slippage_bps_meaning": "How much worse the average price received was than the best price on offer, "
                                    "in hundredths of a percent.",
            "filled": flag(row, "offramp_filled"),
        },
        "book_detail": "aggregates_only",
        "book_detail_meaning": "The individual order book levels this calculation actually walked through are not "
                                "saved -- only the prices and the amount filled that they produced. Full order book "
                                "detail is a separate, later item.",
        "collected_at": row.get("ts"),
    }

    fees = {
        "onramp": {
            "venue": onramp_venue,
            "venue_display": venue_display(onramp_venue),
            "taker_bps": on_cfg.get("taker_bps"),
            "taker_bps_meaning": "This exchange's fee for buying the stablecoin with a market order (take "
                                  "whatever price is on offer right now).",
            "maker_bps": on_cfg.get("maker_bps"),
            "maker_bps_meaning": "This exchange's fee for buying the stablecoin with a limit order (set a price "
                                  "and wait for it to fill).",
            "verified": on_cfg.get("verified"),
        },
        "offramp": {
            "venue": offramp_venue,
            "venue_display": venue_display(offramp_venue),
            "taker_bps": off_cfg.get("taker_bps"),
            "taker_bps_meaning": "This exchange's fee for selling the stablecoin with a market order.",
            "maker_bps": off_cfg.get("maker_bps"),
            "maker_bps_meaning": "This exchange's fee for selling the stablecoin with a limit order.",
            "verified": off_cfg.get("verified"),
        },
        "network": {
            "value_stable": num(row, "network_fee_stable"),
            "value_stable_meaning": "The fee actually paid to move the stablecoin itself on its own network, in "
                                     "units of the stablecoin, at this amount.",
            "venue": onramp_venue,
            "venue_display": venue_display(onramp_venue),
        },
        "deposit": ramp_leg("deposit", src, cfg.get("deposit"), ramp_row, "deposit_measured", on_cfg.get("venue")),
        "withdrawal": ramp_leg("withdrawal", dst, cfg.get("withdrawal"), ramp_row, "withdrawal_measured",
                                off_cfg.get("venue")),
    }

    legs = None
    if wf_row is not None and ramp_row is not None:
        legs = {
            "deposit_bps": num(ramp_row, "wf_deposit_bps"),
            "buy_bps": num(wf_row, "wf_buy_bps"),
            "move_bps": num(wf_row, "wf_move_bps"),
            "sell_bps": num(wf_row, "wf_sell_bps"),
            "withdrawal_bps": num(ramp_row, "wf_withdrawal_bps"),
            "legs_meaning": "The market-order total, split into the five real steps money moves through: getting "
                             "the sending currency onto the first exchange, buying the stablecoin, sending it on "
                             "its own network, selling the stablecoin, and getting the receiving currency into a "
                             "bank account. These five numbers add up to result_pct exactly, to the cent, by "
                             "construction -- not approximately.",
        }

    computation = {
        "taker": {
            "result_pct": num(row, "cost_bps_taker"),
            "result_pct_meaning": "The market-order total cost of the whole transfer, in hundredths of a percent "
                                   "of the amount sent, every fee above already added in. Matches data/samples.csv "
                                   "row's own cost_bps_taker for this exact sample.",
            "legs": legs,
            "legs_available": legs is not None,
        },
        "maker": {
            "result_pct": num(row, "cost_bps_maker"),
            "result_pct_meaning": "The limit-order total cost of the whole transfer, in hundredths of a percent of "
                                   "the amount sent. Matches data/samples.csv row's own cost_bps_maker for this "
                                   "exact sample.",
            "legs": None,
            "legs_available": False,
            "legs_note": "This site only breaks the market-order total into step-by-step legs. The limit-order "
                          "total above is a real, separately computed number, just not decomposed the same way.",
        },
    }

    source_files = ["data/samples.csv"]
    if wf_row is not None:
        source_files.append("data/corridor_waterfall.csv")
    if ramp_row is not None:
        source_files.append("data/ramp_waterfall.csv")

    return {
        "corridor": corridor,
        "notional_src": notional_src,
        "src_ccy": src,
        "dst_ccy": dst,
        "hour_utc": hour_of(row.get("ts")),
        "ts": row.get("ts"),
        "evidence": evidence,
        "fees": fees,
        "computation": computation,
        "source_files": sorted(set(source_files)),
    }


def build():
    sample_rows = rows(SAMPLES)
    latest = latest_rows_by_key(sample_rows)
    wf_by_key = index_waterfall(CORRIDOR_WATERFALL)
    ramp_by_key = index_waterfall(RAMP_WATERFALL)

    out = {}
    for (corridor, notional_src), row in latest.items():
        cfg = collector.CORRIDORS.get(corridor)
        if cfg is None:
            continue  # a corridor this receipt doesn't know the fee constants for -- never guessed
        ts = row.get("ts")
        wf_row = wf_by_key.get((ts, corridor, notional_src))
        ramp_row = ramp_by_key.get((ts, corridor, notional_src))
        filename = f"{corridor_slug(corridor)}_{notional_src}_{hour_of(ts)}"
        out[filename] = build_receipt(corridor, notional_src, row, wf_row, ramp_row, cfg)
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
        print(f"  [error] cannot write corridor receipts: {e}", file=sys.stderr)
        sys.exit(1)

    n_with_legs = sum(1 for r in receipts.values() if r["computation"]["taker"]["legs_available"])
    print(f"  wrote {len(receipts)} corridor receipts -> data/corridor_receipts/ "
          f"({n_with_legs} with a step-by-step market-order breakdown)")


if __name__ == "__main__":
    main()
