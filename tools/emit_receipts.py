#!/usr/bin/env python3
"""The receipt behind every number: data/receipts/<CCY>.json (SEB-56).

`data/countries/<CCY>.json` says what a dollar costs. This says WHY: the
individual rows the figure was built from, traced back far enough that a
stranger can re-do the arithmetic themselves. One file per currency, for the
hour `tools/emit_countries.py` last computed -- published or withheld, since
a withheld currency has just as real a receipt as a published one, only the
last line reads "not published" instead of a number.

Every field is read from a file already in data/: `data/countries/<CCY>.json`
(the computed figure, written by emit_countries.py, which must run first),
and beneath it the CSVs that figure was built from -- `data/p2p_basis.csv` or
`data/basis.csv` for the evidence, `data/fx_rates.csv` for the official rate,
`data/p2p_sides.csv` for the actual buy-side ad count the v1.1 rule tests.
Nothing here is a fresh measurement; this only re-opens files the collectors
already wrote and shows their rows next to the number they produced.

Five things every receipt carries, per the issue:
  evidence        count of offers/ads, the median, the source kind, when it
                   was collected
  official_rate   the denominator: value, timestamp, source file
  computation     numerator, denominator, result -- the arithmetic itself
  evidence_rule   required vs. actual, and whether it passed
  source_files    every CSV/JSON a number in this receipt came from

Per-offer detail (SEB-56, second half). `data/p2p_offers.csv` is a new
sidecar that only exists from the collector run this shipped in forward --
there is no Binance endpoint for past ad prices, so an hour collected before
the sidecar existed has no offers to show and never will. A receipt for such
an hour says `"offer_detail": "aggregates_only"` and carries no `offers` list;
it does NOT reconstruct one from the median, because a median cannot be
un-averaged back into the ads that made it. `"offer_detail": "per_offer"`
appears only where real rows were found for that exact currency and hour.

Where a currency was withheld (the v1.1 evidence rule failed, or a board's
own price was never collected this hour), `computation.result_pct` is still
shown when the raw price exists to compute it from -- the same arithmetic
`data/countries/<CCY>.json` already runs for `round_trip_pct` on a withheld
row. `published` says whether that number is the one on the site; a withheld
receipt's result never appears anywhere published, only here, so the
arithmetic behind an unpublished figure is still checkable.

Stdlib only. No wall clock: `computed_at` is copied from the country file, so
an unchanged dataset regenerates byte-identical receipts, same as every other
emitter in this repo. Exits non-zero only if it cannot write.

Usage: python3 tools/emit_receipts.py
"""

import csv
import datetime as dt
import html
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
COPY_PATH = os.path.join(HERE, "copy.json")
COUNTRIES_DIR = os.path.join(DATA, "countries")
P2P = os.path.join(DATA, "p2p_basis.csv")
BASIS = os.path.join(DATA, "basis.csv")
FX = os.path.join(DATA, "fx_rates.csv")
SIDES = os.path.join(DATA, "p2p_sides.csv")
OFFERS = os.path.join(DATA, "p2p_offers.csv")
OUT_DIR = os.path.join(DATA, "receipts")

MIN_BUY_ADS = 10  # the v1.1 evidence rule -- see METHODOLOGY.md


# ------------------------------------------------------------- parsing
def rows(path):
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


def flag(row, key):
    return (row.get(key) or "").strip().lower() == "true"


def parse_ts(s):
    try:
        t = dt.datetime.fromisoformat((s or "").strip())
    except ValueError:
        return None
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t


def hour_of(ts):
    return ts.replace(minute=0, second=0, microsecond=0)


# ------------------------------------------------------------ row lookups
def p2p_rows_for(ccy, hour):
    """Every data/p2p_basis.csv row for this currency in this UTC hour."""
    out = []
    for r in rows(P2P):
        t = parse_ts(r.get("ts_utc"))
        if r.get("ccy") == ccy and t is not None and hour_of(t) == hour:
            out.append(r)
    return out


def basis_rows_for(ccy, hour, venues):
    """data/basis.csv rows for this currency, hour and venue set."""
    out = []
    for r in rows(BASIS):
        t = parse_ts(r.get("ts_utc"))
        if (r.get("ccy") == ccy and t is not None and hour_of(t) == hour
                and (r.get("venue") or "") in venues):
            out.append(r)
    return out


def sides_row_for(ccy, hour):
    for r in rows(SIDES):
        t = parse_ts(r.get("ts_utc"))
        if r.get("ccy") == ccy and t is not None and hour_of(t) == hour:
            return r
    return None


def offers_for(ccy, hour):
    """Individual ad prices for this currency and hour, or [] if the sidecar
    holds none -- either because the hour predates it, or because no offer
    happened to land in this run. Never invented either way."""
    out = []
    for r in rows(OFFERS):
        t = parse_ts(r.get("ts_utc"))
        if r.get("ccy") == ccy and t is not None and hour_of(t) == hour:
            price = num(r, "price")
            side = r.get("side")
            if side and price is not None:
                out.append({"side": side, "price": price})
    return out


def fx_row_for(ccy, hour):
    """The data/fx_rates.csv row in force at `hour` -- newest at or before it,
    same "a rate holds until the next one is published" rule emit_countries.py
    uses, but this keeps the raw row (so the receipt can show its own
    timestamp, not just the value)."""
    series = []
    for r in rows(FX):
        t = parse_ts(r.get("ts_utc"))
        if r.get("ccy") == ccy and t is not None and num(r, "fx_mid_per_usd") is not None:
            series.append((hour_of(t), t, r))
    series.sort(key=lambda x: x[0])
    chosen = None
    for h, t, r in series:
        if h <= hour:
            chosen = (t, r)
        else:
            break
    if chosen is None:
        same_day = [(t, r) for h, t, r in series if h.date() == hour.date()]
        chosen = same_day[0] if same_day else None
    return chosen  # (ts, row) or None


# --------------------------------------------------------------- receipt
def evidence_and_rule(doc, ccy, hour):
    """The evidence summary and the evidence-rule check, per source layer.

    A p2p-sourced figure (published as `p2p_buy_median`, or withheld -- both
    read `data/p2p_basis.csv`) is the only layer the v1.1 minimum-ad rule
    governs. An order-book or broker figure is evidenced by how many venues
    priced it instead, and was never subject to withholding -- if it is in
    the country file at all, it published. `p2p_fallback` (Nigeria's
    CoinGecko stand-in, SEB-8) is a single aggregated price with no ad count
    of its own, so the ad rule does not apply to it either.
    """
    source_file = doc.get("source_file")
    source_class = doc.get("source_class")

    if source_file == "data/basis.csv":
        venues = {v.get("venue") for v in (doc.get("venues") or []) if v.get("venue")}
        raw = basis_rows_for(ccy, hour, venues)
        bids = [num(r, "usdt_bid") for r in raw if num(r, "usdt_bid") is not None]
        collected_at = max((r.get("ts_utc") for r in raw), default=None)
        evidence = {
            "source_kind": source_class,
            "source_words": doc.get("source_words"),
            "n_offers": doc.get("n_sources"),
            "buy_median": doc.get("buy_price"),
            "sell_median": round(statistics.median(bids), 8) if bids else None,
            "collected_at": collected_at,
            "offer_detail": "aggregates_only",
            "offers": None,
        }
        rule = {
            "applies": False,
            "note": ("the v1.1 minimum-ad rule governs peer-to-peer sources only; "
                     "this figure comes from an order book or broker quote, "
                     "evidenced by venue count instead"),
            "n_venues_required": 1,
            "n_venues_actual": doc.get("n_sources"),
            "passed": True,
            "reason": None,
        }
        return evidence, rule, ["data/basis.csv"]

    # source_file == "data/p2p_basis.csv" (published p2p, fallback, or withheld)
    # `buy_price` is set at the top level whenever the hour published --
    # p2p_buy_median and p2p_fallback both set it -- and is absent only when
    # withheld, which is exactly when `withheld_buy_price` takes over.
    raw = p2p_rows_for(ccy, hour)
    price = doc.get("buy_price")
    withheld_price = doc.get("withheld_buy_price")
    match = None
    for r in raw:
        rp = num(r, "buy_median") if source_class != "p2p_fallback" else num(r, "mid")
        target = price if price is not None else withheld_price
        if target is not None and rp is not None and abs(rp - target) < 1e-6:
            match = r
            break
    if match is None and raw:
        match = raw[0]

    offers = offers_for(ccy, hour)
    n_offer_files = ["data/p2p_basis.csv"]

    if source_class == "p2p_fallback":
        evidence = {
            "source_kind": source_class,
            "source_words": doc.get("source_words"),
            "n_offers": None,
            "buy_median": num(match, "mid") if match else None,
            "sell_median": None,
            "collected_at": match.get("ts_utc") if match else None,
            "offer_detail": "aggregates_only",
            "offers": None,
        }
        rule = {
            "applies": False,
            "note": ("a single aggregated price from an independent source "
                     "(SEB-8), not a two-sided ad board -- no ad count to test"),
            "n_venues_required": None, "n_venues_actual": None,
            "passed": True, "reason": None,
        }
        return evidence, rule, n_offer_files

    sides = sides_row_for(ccy, hour)
    buy_ads_estimated = False
    if sides is not None:
        n_buy = int(num(sides, "n_buy") or 0)
        n_offer_files.append("data/p2p_sides.csv")
    else:
        # Same conservative stand-in as emit_countries.py: rows from before
        # the sides sidecar existed carry only the two sides summed.
        total = num(match, "n_ads") if match else None
        n_buy = MIN_BUY_ADS if (total or 0) >= MIN_BUY_ADS * 2 else 0
        buy_ads_estimated = True

    buy_median = num(match, "buy_median") if match else None
    sell_median = num(match, "sell_median") if match else None
    passed = source_class == "p2p_buy_median"
    buy_at_or_above_sell = (
        None if buy_median is None or sell_median is None
        else buy_median >= sell_median)

    evidence = {
        "source_kind": source_class,
        "source_words": doc.get("source_words"),
        "n_offers": n_buy,
        "buy_median": buy_median,
        "sell_median": sell_median,
        "collected_at": match.get("ts_utc") if match else None,
        "offer_detail": "per_offer" if offers else "aggregates_only",
        "offers": offers or None,
    }
    rule = {
        "applies": True,
        "note": None,
        "min_buy_ads_required": MIN_BUY_ADS,
        "buy_ads_actual": n_buy,
        "buy_ads_estimated": buy_ads_estimated,
        "buy_at_or_above_sell": buy_at_or_above_sell,
        "passed": passed,
        "reason": doc.get("no_value_reason"),
    }
    if offers:
        n_offer_files.append("data/p2p_offers.csv")
    return evidence, rule, n_offer_files


def build_receipt(ccy, doc):
    hour = parse_ts(doc.get("hour_utc"))
    evidence, rule, evidence_files = evidence_and_rule(doc, ccy, hour)

    den = doc.get("denominator") or {}
    fx_hit = fx_row_for(ccy, hour) if hour is not None else None
    if fx_hit is not None:
        fx_ts, fx_row = fx_hit
        official_rate = {
            "value": den.get("rate_per_usd"),
            "timestamp": fx_ts.isoformat(),
            "source": fx_row.get("source") or den.get("source"),
            "class": den.get("class"),
            "source_file": "data/fx_rates.csv",
        }
        rate_file = "data/fx_rates.csv"
    else:
        # No data/fx_rates.csv row covers this hour -- the rate came from the
        # price row itself (pre-fx_rates.csv history; see emit_countries.py,
        # `fx_for`). Said plainly rather than pointed at a file with no row.
        official_rate = {
            "value": den.get("rate_per_usd"),
            "timestamp": evidence.get("collected_at"),
            "source": den.get("source"),
            "class": den.get("class"),
            "source_file": doc.get("source_file"),
        }
        rate_file = doc.get("source_file")

    numerator = doc.get("buy_price")
    if numerator is None:
        numerator = doc.get("withheld_buy_price")
    denominator = den.get("rate_per_usd")
    published = doc.get("index_pct") is not None
    if published:
        result_pct = doc.get("index_pct")
    elif numerator is not None and denominator:
        result_pct = round((numerator / denominator - 1) * 100, 4)
    else:
        result_pct = None

    source_files = sorted(set(evidence_files + [rate_file, "data/countries/%s.json" % ccy]))

    return {
        "ccy": ccy,
        "country": doc.get("country"),
        "hour_utc": doc.get("hour_utc"),
        "computed_at": doc.get("computed_at"),
        "index_version": doc.get("index_version"),
        "published": published,
        "not_published_reason": None if published else doc.get("no_value_reason"),
        # A number outside the sanity band is still computed and shown on its
        # own country page with a banner -- it is only left out of the RANKED
        # index until checked (METHODOLOGY, "Sanity bands"). `published`
        # above answers "was a number computed", which is still true here;
        # these two say the rest, straight from the same country file.
        "unverified": bool(doc.get("unverified")),
        "unverified_reason": doc.get("unverified_reason"),
        "outlier_checked": doc.get("outlier_checked"),
        "evidence": evidence,
        "official_rate": official_rate,
        "computation": {
            "numerator": numerator,
            "numerator_meaning": "price to buy one dollar locally",
            "denominator": denominator,
            "denominator_meaning": "the official rate, local currency per dollar",
            "formula": "(numerator / denominator - 1) * 100",
            "result_pct": result_pct,
        },
        "evidence_rule": rule,
        "source_files": source_files,
    }


# ------------------------------------------------- no-JS / reduced-motion
# SEB-57's overlay (receipt.js) is one implementation of this receipt; a
# reader with no JavaScript needs the same four steps with no interaction at
# all. Rather than a second, divergent description of the receipt, this
# mirrors receipt.js's own buildSteps() field-for-field -- same copy.json
# keys, same wording rules -- so the no-JS rendering and the JS overlay can
# never say something different about the same number.
_copy_cache = None


def _copy():
    """copy.json's `receipt` key, read once. A missing file or key fails
    loudly (the caller sees the exception), same as chart.py's own reader --
    no page ships with a made-up label standing in for a missing one."""
    global _copy_cache
    if _copy_cache is None:
        with open(COPY_PATH, encoding="utf-8") as f:
            _copy_cache = json.load(f)["receipt"]
    return _copy_cache


def _template(s, vals):
    if not s:
        return ""
    return re.sub(r"\{(\w+)\}",
                   lambda m: "" if vals.get(m.group(1)) is None else str(vals[m.group(1)]),
                   s)


def _fmt_num(v):
    if v is None:
        return "—"
    s = f"{float(v):,.6f}".rstrip("0").rstrip(".")
    return s if s and s != "-" else "0"


def _fmt_when(iso):
    if not iso:
        return "—"
    try:
        t = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return t.strftime("%Y-%m-%d %H:%M") + " UTC"


def _evidence_count_words(kind, n):
    """Mirrors receipt.js's evidenceCountWords() -- word choice only, the
    same kind of small presentational duplication chart.js already carries
    for chart.py's geometry."""
    n = n or 0
    if kind in ("order_book_median", "order_book_single"):
        return f"{n} order book" + ("" if n == 1 else "s")
    if kind in ("broker_median", "broker_single"):
        return f"{n} broker quote" + ("" if n == 1 else "s")
    if kind == "p2p_buy_median":
        return "1 person selling" if n == 1 else f"{n} people selling"
    if kind == "p2p_fallback":
        return "an independent price check"
    return None


def _step_files(r):
    rate_file = (r.get("official_rate") or {}).get("source_file")
    files = r.get("source_files") or []
    country_file = next((f for f in files if f.startswith("data/countries/")), None)
    evidence_files = [f for f in files if f != rate_file and f != country_file]
    verdict_file = (next((f for f in evidence_files if "p2p_sides" in f), None)
                     or (evidence_files[0] if evidence_files else country_file))
    return {
        "evidence": evidence_files if evidence_files else ([country_file] if country_file else []),
        "rate": [rate_file] if rate_file else [],
        "math": [country_file] if country_file else [],
        "verdict": [verdict_file] if verdict_file else [],
    }


def build_steps(receipt, copy, display_value=None):
    """The same four {label, text, files} steps receipt.js's buildSteps()
    renders into the overlay -- built here so the no-JS page can show them
    without a click, an animation, or a second fetch."""
    files = _step_files(receipt)
    ev = receipt.get("evidence") or {}
    rate = receipt.get("official_rate") or {}
    comp = receipt.get("computation") or {}
    rule = receipt.get("evidence_rule") or {}

    words = _evidence_count_words(ev.get("source_kind"), ev.get("n_offers")) or ev.get("source_words") or ""
    evidence_text = _template(copy.get("evidenceSentenceTemplate"),
                               {"words": words, "price": _fmt_num(ev.get("buy_median")), "ccy": receipt.get("ccy")})
    evidence_note = copy.get("evidenceOffersNote") if ev.get("offer_detail") == "per_offer" else copy.get("evidenceAggregateNote")
    collected = _template(copy.get("evidenceCollectedTemplate"), {"when": _fmt_when(ev.get("collected_at"))})

    rate_class = rate.get("class")
    rate_word = (copy.get("rateManaged") if rate_class == "managed"
                 else copy.get("ratePegged") if rate_class == "pegged"
                 else copy.get("rateUnmaintained") if rate_class == "unmaintained"
                 else copy.get("rateMarket"))
    rate_text = _template(copy.get("rateSentenceTemplate"),
                           {"value": _fmt_num(rate.get("value")), "ccy": receipt.get("ccy"), "source": rate.get("source") or ""})

    math_text = _template(copy.get("mathSentenceTemplate"),
                           {"numerator": _fmt_num(comp.get("numerator")), "ccy": receipt.get("ccy"),
                            "denominator": _fmt_num(comp.get("denominator"))})
    math_result = _template(copy.get("mathResultTemplate"),
                             {"result": display_value if display_value is not None else _fmt_num(comp.get("result_pct"))})

    verdict_detail = ""
    if receipt.get("published"):
        verdict_text = copy.get("verdictPublished")
        if rule.get("applies"):
            verdict_detail = _template(copy.get("verdictRuleDetailTemplate"),
                                        {"actual": rule.get("buy_ads_actual"), "required": rule.get("min_buy_ads_required")})
        else:
            verdict_detail = rule.get("note") or ""
    else:
        verdict_text = _template(copy.get("verdictWithheldTemplate"), {"reason": receipt.get("not_published_reason") or ""})

    return [
        {"label": copy.get("step1Label"), "text": " ".join(x for x in (evidence_text, evidence_note, collected) if x), "files": files["evidence"]},
        {"label": copy.get("step2Label"), "text": " ".join(x for x in (rate_text, rate_word) if x), "files": files["rate"]},
        {"label": copy.get("step3Label"), "text": " ".join(x for x in (math_text, math_result) if x), "files": files["math"]},
        {"label": copy.get("step4Label"), "text": " ".join(x for x in (verdict_text, verdict_detail) if x), "files": files["verdict"]},
    ]


def render_static_html(receipt, display_value, link_prefix="../"):
    """The `<noscript>` fragment for a published receipt: all four steps
    rendered at once, no animation, no click needed -- what a reader with no
    JavaScript, or `prefers-reduced-motion`, gets instead of the overlay.
    Never called for a withheld number: c/<ccy>.html only wires a receipt to
    the one figure it actually shows, same rule receipt.js's click handler
    follows (SEB-57)."""
    copy = _copy()
    steps = build_steps(receipt, copy, display_value)

    def links(files):
        return " · ".join(
            f'<a href="{link_prefix}{html.escape(f)}">{html.escape(f)}</a>' for f in (files or []))

    items = []
    for i, step in enumerate(steps, 1):
        file_links = links(step["files"])
        items.append(
            '<li class="receipt-static-step">'
            f'<span class="receipt-static-num">{i}</span>'
            f'<span class="receipt-static-label">{html.escape(step["label"] or "")}</span>'
            f'<span class="receipt-static-text">{html.escape(step["text"] or "")}</span>'
            + (f'<span class="receipt-static-file">{file_links}</span>' if file_links else "")
            + "</li>")

    return (
        '<noscript><div class="receipt-static">'
        f'<p class="receipt-static-title">{html.escape(copy.get("title") or "")}</p>'
        f'<ol class="receipt-static-steps">{"".join(items)}</ol>'
        f'<p class="receipt-static-raw"><b>{html.escape(copy.get("rawFilesLabel") or "")}</b> '
        f'{links(receipt.get("source_files"))}</p>'
        "</div></noscript>"
    )


def build():
    if not os.path.isdir(COUNTRIES_DIR):
        return {}
    out = {}
    for name in sorted(os.listdir(COUNTRIES_DIR)):
        if not name.endswith(".json"):
            continue
        ccy = name[:-5]
        try:
            with open(os.path.join(COUNTRIES_DIR, name)) as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        out[ccy] = build_receipt(ccy, doc)
    return out


def main():
    receipts = build()
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        for ccy, receipt in receipts.items():
            with open(os.path.join(OUT_DIR, f"{ccy}.json"), "w") as f:
                json.dump(receipt, f, indent=2, sort_keys=True)
                f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write receipts: {e}", file=sys.stderr)
        sys.exit(1)

    n_published = sum(1 for r in receipts.values() if r["published"])
    n_offer_detail = sum(1 for r in receipts.values()
                          if r["evidence"]["offer_detail"] == "per_offer")
    print(f"  wrote {len(receipts)} receipts -> data/receipts/ "
          f"({n_published} published, {len(receipts) - n_published} withheld)")
    print(f"  {n_offer_detail} of {len(receipts)} carry per-offer detail "
          f"(data/p2p_offers.csv starts {'-- no rows yet' if not n_offer_detail else 'here'})")


if __name__ == "__main__":
    main()
