#!/usr/bin/env python3
"""D1 (v1 freeze and ship brief): the homepage's headline, waterfall and
corridor table, computed from data/samples.csv -- never typed by hand.

Writes data/corridor_summary.json:

  headline            the data-driven sentence itself, plus the numbers it
                       was built from, so the page never has to re-derive it
                       and a reader can check the arithmetic against
                       `n`/`wins`/`loss_rate_pct`.
  waterfall            SGD->PHP at S$5,000: the five real terms of the
                       decomposition (on-ramp basis, on-ramp fee, network
                       fee, off-ramp basis, off-ramp fee) plus the total,
                       median across every real row at that rung -- the
                       same arithmetic README.md's own headline cites.
  corridors            one entry per tracked corridor: median taker cost,
                       median best-incumbent-fiat cost, and the real win
                       rate, all at the 5,000-unit rung (S$5,000 /
                       A$5,000 / NZ$5,000 / US$5,000 -- the same size on
                       every corridor's own ladder).

Every figure here is a median across real historical rows, computed fresh
on every run. Nothing is typed, nothing is cached from a prior run.

Stdlib only.
"""

import csv
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SAMPLES = os.path.join(DATA, "samples.csv")
PROVIDERS_LATEST = os.path.join(DATA, "providers_latest.json")
OUT = os.path.join(DATA, "corridor_summary.json")

RUNG = "5000"
CORRIDORS = ["SGD->PHP", "AUD->PHP", "NZD->PHP", "USD->MXN"]
WATERFALL_CORRIDOR = "SGD->PHP"


def median(values):
    if not values:
        return None
    s = sorted(values)
    return s[len(s) // 2]


def _float(row, key):
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_route_words():
    if not os.path.exists(PROVIDERS_LATEST):
        return {}
    with open(PROVIDERS_LATEST) as f:
        doc = json.load(f)
    return {k: v.get("route_words", k) for k, v in (doc.get("corridors") or {}).items()}


def corridor_stats(rows, corridor):
    cr = [r for r in rows if r["corridor"] == corridor and r["source_ok"] == "True"
          and r.get("notional_src") == RUNG]
    n = len(cr)
    if n == 0:
        return None
    taker = [x for x in (_float(r, "cost_bps_taker") for r in cr) if x is not None]
    maker = [x for x in (_float(r, "cost_bps_maker") for r in cr) if x is not None]
    baseline = [x for x in (_float(r, "baseline_cost_bps") for r in cr) if x is not None]
    wins_taker = sum(1 for r in cr if r.get("crypto_wins_taker") == "True")
    wins_maker = sum(1 for r in cr if r.get("crypto_wins_maker") == "True")
    return {
        "corridor": corridor,
        "n": n,
        "taker_cost_bps_median": median(taker),
        "maker_cost_bps_median": median(maker),
        "baseline_cost_bps_median": median(baseline),
        "win_rate_taker_pct": round(100 * wins_taker / n, 1),
        "win_rate_maker_pct": round(100 * wins_maker / n, 1),
    }


def waterfall(rows, corridor, route_words=None):
    """Median of each real decomposition term, at the RUNG size, taker
    regime -- the same five-term arithmetic README.md's headline cites,
    not re-derived, just reported as the historical median.
    """
    cr = [r for r in rows if r["corridor"] == corridor and r["source_ok"] == "True"
          and r.get("notional_src") == RUNG]
    terms = {
        "onramp_basis_bps": [], "fee_on_taker_bps": [], "network_fee_bps": [],
        "offramp_basis_bps": [], "fee_off_taker_bps": [], "cost_bps_taker": [],
        "baseline_cost_bps": [],
    }
    for r in cr:
        for key in ("onramp_basis_bps", "fee_on_taker_bps", "offramp_basis_bps",
                    "fee_off_taker_bps", "cost_bps_taker", "baseline_cost_bps"):
            v = _float(r, key)
            if v is not None:
                terms[key].append(v)
        # network_fee_stable is recorded in stablecoin units, not bps.
        # Converted the same way corridor.html's own waterfall already
        # does (netBps()): as bps of the gross stablecoin actually bought
        # (notional_src / onramp_vwap), not of the notional itself -- one
        # convention, not two pages disagreeing on what "bps" means here.
        netfee = _float(r, "network_fee_stable")
        notional = _float(r, "notional_src")
        on_vwap = _float(r, "onramp_vwap")
        if netfee is not None and notional and on_vwap:
            gross = notional / on_vwap
            if gross:
                terms["network_fee_bps"].append(round(netfee / gross * 1e4, 4))
    if not terms["cost_bps_taker"]:
        return None
    return {
        "corridor": corridor,
        "route_words": route_words or corridor,
        "rung_src": int(RUNG),
        "n": len(terms["cost_bps_taker"]),
        "onramp_basis_bps": median(terms["onramp_basis_bps"]),
        "onramp_fee_bps": median(terms["fee_on_taker_bps"]),
        "network_fee_bps": median(terms["network_fee_bps"]),
        "offramp_basis_bps": median(terms["offramp_basis_bps"]),
        "offramp_fee_bps": median(terms["fee_off_taker_bps"]),
        "total_cost_bps": median(terms["cost_bps_taker"]),
        "baseline_cost_bps": median(terms["baseline_cost_bps"]),
    }


def build():
    rows = list(csv.DictReader(open(SAMPLES)))
    route_words = load_route_words()

    corridor_rows = []
    for c in CORRIDORS:
        stats = corridor_stats(rows, c)
        if stats:
            stats["route_words"] = route_words.get(c, c)
            corridor_rows.append(stats)

    # ---- the headline stat: real, computed, across every corridor's own
    # RUNG-size rows, taker regime (what a sender gets by default). A
    # corridor only counts as "the interesting exception" if EITHER
    # regime is genuinely competitive -- USD->MXN's taker win rate is
    # itself near zero, same as the other three; it's only maker
    # execution that makes it different, so both regimes are checked,
    # not just the one the headline's own default regime uses.
    competitive = [c for c in corridor_rows
                   if c["win_rate_taker_pct"] >= 10 or c["win_rate_maker_pct"] >= 10]
    losing = [c for c in corridor_rows if c not in competitive]

    losing_rung = [r for r in rows if r["source_ok"] == "True" and r.get("notional_src") == RUNG
                   and r["corridor"] in [c["corridor"] for c in losing]]
    n_all = len(losing_rung)
    wins_all = sum(1 for r in losing_rung if r.get("crypto_wins_taker") == "True")
    loss_rate = round(100 * (n_all - wins_all) / n_all, 1) if n_all else None

    # "fiat rail" and "corridor" are both banned on reader-facing pages
    # (tools/check_page.py's BANNED list / PAGE_BANNED["index.html"]) --
    # this text is what the homepage renders verbatim, so it has to obey
    # the same plain-language rule as any copy.json string, even though
    # it's generated here rather than typed.
    headline = None
    if loss_rate is not None:
        headline = (
            "Stablecoins lost to the best ordinary way to send money in %s%% "
            "of measured hours on %d of %d routes. The rail is nearly free. "
            "The doors are not."
            % (("%.0f" % loss_rate) if loss_rate == int(loss_rate) else ("%.1f" % loss_rate),
               len(losing), len(corridor_rows))
        )

    doc = {
        "status": "ok" if headline else "insufficient_data",
        "rung": int(RUNG),
        "headline": {
            "text": headline,
            "n_hours_measured": n_all,
            "n_hours_stablecoin_won": wins_all,
            "loss_rate_pct": loss_rate,
            "corridors_measured": len(corridor_rows),
            "corridors_losing_almost_always": len(losing),
            "corridors_competitive": [c["corridor"] for c in competitive],
        },
        "waterfall": waterfall(rows, WATERFALL_CORRIDOR, route_words.get(WATERFALL_CORRIDOR)),
        "corridors": corridor_rows,
        "source": ["data/samples.csv", "data/providers_latest.json"],
    }
    return doc


def main():
    doc = build()
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print("  headline:", doc["headline"]["text"])
    for c in doc["corridors"]:
        print("  %-10s taker %.1f vs best-fiat %.1f bps, win rate %.1f%% (n=%d)" % (
            c["corridor"], c["taker_cost_bps_median"], c["baseline_cost_bps_median"],
            c["win_rate_taker_pct"], c["n"]))
    print("  written to", os.path.relpath(OUT, HERE))


if __name__ == "__main__":
    main()
