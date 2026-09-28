#!/usr/bin/env python3
"""D1 (v1 freeze and ship brief): bake the real headline and duel comparison
into index.html's own markup at collection time, so a crawler or a visitor
with JS off sees the actual measurement -- not "Loading this hour's
measurement...", which is what ships otherwise.

Runs AFTER tools/emit_corridor_summary.py, every pass. Idempotent: each run
replaces exactly what the LAST run wrote, using the same id="..." anchors
the client-side JS already targets, so baking twice in a row (or baking
then letting JS re-render on load) never duplicates or drifts. The waterfall
(now a single stacked cost bar, matching the final mockup) stays
client-rendered -- worth building in one place (the browser), not twice.

2026-09-28 reconciliation with the final mockup: the "All 4 routes, in
detail" corridor table (and the functions/copy that built it) is gone --
docs/mockups/home.html never had it, and on a phone its columns ran off the
edge. Its "every provider, every amount" link content stays reachable from
sending-money.html. This pass also fixed the duel comparison's "cheapest
app" figure: it used to look up data/providers_latest.json's single
cheapest CURRENT-hour quote (direct provider quotes included), which could
be a one-hour outlier from a provider like Airwallex or Instarem, not a
real typical price. It now reads baseline_cost_bps_median straight off
data/corridor_summary.json -- the public comparison feed's typical/median-
hour figure, the same one data/corridor_window.json's "best_cost" already
used. See duel_html()'s own docstring for the full before/after.

Day-1 plain-language pass: the headline and sub are fixed, plain sentences
(copy.json home.headline / home.headlineSub), not a sentence assembled from
jargon words -- only the two real numbers in the sub (what the stablecoin
route costs, what the cheapest app costs) and the window they cover are
computed, from data/corridor_summary.json and data/samples.csv, never typed.
Both numbers and the window are ALSO written to data/corridor_window.json,
so index.html's client-side render and any other page that needs the same
figure read the identical file instead of recomputing it -- one source, one
window, per DESIGN.md's plain-language rule.

If data/corridor_summary.json is missing or unmeasurable, this leaves
index.html's existing baked content alone rather than blanking it back to
a loading state -- a real number from an earlier pass outlives a single
failed one, same as every other "gaps stay gaps" rule on this site never
means "erase what was already known."

Stdlib only.
"""

import csv
import datetime as dt
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY = os.path.join(HERE, "data", "corridor_summary.json")
SAMPLES = os.path.join(HERE, "data", "samples.csv")
WINDOW_OUT = os.path.join(HERE, "data", "corridor_window.json")
INDEX_HTML = os.path.join(HERE, "index.html")
INDEX_LATEST = os.path.join(HERE, "data", "index_latest.json")
STREET_DEPTH_LATEST = os.path.join(HERE, "data", "street_depth_latest.json")


def load_json_or_none(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

# Plain currency symbols for the four routes this site prices at this
# level of detail. Labels only, never a number -- same rule as every other
# display map on this site (tools/emit_countries.py's COUNTRY, for one).
SRC_SYMBOL = {"SGD": "S$", "AUD": "A$", "NZD": "NZ$", "USD": "US$"}
SRC_NAME = {"SGD": "Singapore", "AUD": "Australia", "NZD": "New Zealand", "USD": "the US"}
DEST_NAME = {"PHP": "the Philippines", "MXN": "Mexico"}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def money(amount, symbol):
    return symbol + f"{round(amount):,}"


def fmt_date(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def earliest_dates_by_corridor():
    """{corridor: date} -- the real first row's date for each corridor in
    data/samples.csv, so "since August" is never typed: it is read off the
    same file the cost figures come from.
    """
    out = {}
    if not os.path.exists(SAMPLES):
        return out
    with open(SAMPLES, newline="") as f:
        for row in csv.DictReader(f):
            corridor = row.get("corridor")
            ts = row.get("ts")
            if not corridor or not ts:
                continue
            try:
                d = dt.datetime.fromisoformat(ts.strip()).date()
            except ValueError:
                continue
            if corridor not in out or d < out[corridor]:
                out[corridor] = d
    return out


def build_window(doc):
    """One row per tracked corridor: the real send amount, what the
    stablecoin route and the cheapest app cost at it, the window ("typical
    over N hours since D Mon YYYY") that window covers, and the plain route
    words -- everything a page needs to state a headline number and its
    window from ONE file, never recomputed.
    """
    rung = doc.get("rung")
    since_by_corridor = earliest_dates_by_corridor()
    out = {}
    for c in doc.get("corridors", []):
        corridor = c.get("corridor")
        src = (corridor or "").split("->")[0]
        symbol = SRC_SYMBOL.get(src, src + " ")
        dest = (c.get("route_words") or "").split(" to ")[-1] or "the destination country"
        n = c.get("n")
        since = since_by_corridor.get(corridor)
        stable_bps = c.get("taker_cost_bps_median")
        best_bps = c.get("baseline_cost_bps_median")
        row = {
            "corridor": corridor,
            "route_words": c.get("route_words"),
            "dest": dest,
            "rung": rung,
            "send_amount": money(rung, symbol) if rung is not None else None,
            "n_hours": n,
            "since": since.isoformat() if since else None,
        }
        if rung is not None and stable_bps is not None:
            row["stable_cost"] = round(rung * stable_bps / 10000, 2)
            row["stable_cost_words"] = money(rung * stable_bps / 10000, symbol)
        if rung is not None and best_bps is not None:
            row["best_cost"] = round(rung * best_bps / 10000, 2)
            row["best_cost_words"] = money(rung * best_bps / 10000, symbol)
        if since:
            row["window"] = f"typical hour since {fmt_date(since)}"
        else:
            row["window"] = "typical hour"
        out[corridor] = row
    return out


def sub_html(home_copy, n_countries):
    """The plain, fixed sub sentence (copy.json home.headlineSub), with its
    one real count -- how many countries we price a street dollar in --
    filled in live from data/index_latest.json, never typed. The sentence
    itself carries a real <a> to how-it-works.html, so this is NOT html-
    escaped as a whole (only the numeric substitution would need it, and a
    plain digit string never needs escaping).
    """
    tmpl = home_copy.get("headlineSub", "")
    return tmpl.replace("{n_countries}", str(n_countries) if n_countries is not None else "")


def load_index_latest():
    """The parsed data/index_latest.json doc, or None if it doesn't exist
    yet -- the one file both count_countries() and build_premium_strip()
    read, so neither ever recomputes a country count or a premium figure
    from a second, independent source.
    """
    if not os.path.exists(INDEX_LATEST):
        return None
    with open(INDEX_LATEST) as f:
        return json.load(f)


def count_countries():
    """How many countries have a priced street-dollar rate this hour --
    read from data/index_latest.json's own "countries" list (the priced
    ones; "withheld" is counted separately), the same file the-index.html
    reads for the identical count.
    """
    doc = load_index_latest()
    if doc is None:
        return None
    countries = doc.get("countries")
    return len(countries) if countries is not None else None


# Phase 3: "Where the line runs" -- ranked bar list of countries by
# street-dollar premium over official rate, biggest first. Top PREMIUM_TOP_N
# shown; each row: country name | proportional bar | gap%. Built ONLY from
# data/index_latest.json -- no new data collection, additive-only per VISION.md.
# Bar width uses log1p scaling so near-zero countries don't all render as
# one-pixel slivers.
PREMIUM_CAP = 100.0
PREMIUM_TOP_N = 10

# The baked SVG has no real viewport to measure (no JS has run yet, so this
# is what a crawler or a JS-off visitor sees, and what a visitor on any
# device sees for the instant before index.html's own <script> re-renders
# it at the real container width -- see renderPremiumStrip() there). A
# hardcoded 800-wide viewBox scaled to fit a ~290px mobile card shrank
# 13px/12px text down to an effective ~4.7px (SEB-reported). Baking at a
# mobile-safe canonical width instead means the worst case (mobile, no JS)
# still renders real, legible text; a wider screen's client-side render
# then corrects it back UP to that screen's own real width. 320 is the
# narrowest real content width index.html's own #premiumStripSection card
# renders at on a 320px-wide viewport (the standard small-phone baseline):
# 320 - 2*24 (lead-section padding) - 2*18 (card padding) - 2*1 (card
# border) = 234. A wider phone (375px+) then scales this UP, not down, so
# text only ever renders at or above its nominal size before JS corrects
# the viewBox to the real width.
PREMIUM_BAKE_W = 234


def _home_rows(idx_doc):
    """Every country with a real 24h median -- data/index_latest.json's
    "countries" (this hour's priced ones) PLUS "withheld" rows that still
    carry a median_24h_pct (this hour's single reading failed the evidence
    bar, e.g. a thin overnight P2P board, but the trailing day did not).
    This is the merged Sebastian's 2026-09-28 correction (item 1) asked
    for: the home chart shouldn't drop a country for the hour just because
    its single latest reading was thin, when 23 of its last 24 hours were
    real evidence. Each row's "gap_pct" is median_24h_pct, falling back to
    index_pct only for the rare row with fewer than 1 real hour behind it
    (median_24h_by_ccy returns None only then).
    """
    if idx_doc is None:
        return []
    rows = []
    for c in (idx_doc.get("countries") or []) + (idx_doc.get("withheld") or []):
        gap = c.get("median_24h_pct")
        if gap is None:
            gap = c.get("index_pct")
        if gap is None:
            continue
        rows.append(dict(c, gap_pct=gap))
    return rows


def _priced_sorted(rows, exclude_pegged):
    exclude = ("pegged",) if exclude_pegged else ()
    return sorted(
        [c for c in rows if c.get("denominator_class") not in exclude],
        key=lambda c: c.get("gap_pct", 0.0),
        reverse=True,
    )


# Sebastian's 2026-09-28 correction, item 2: this used to bake a second,
# demoted gaps chart here (the 10 widest gaps this hour). One country chart
# is enough -- the lead chart below now covers the same ground with the
# 24h median -- so this section is now a single static link line, built
# from a fixed copy.json string, not from index_latest.json at all.
def see_all_countries_line(home_copy):
    return ('<div class="strip-note"><a href="./the-index.html" style="font-weight:600;color:#0B0B0B">'
            + esc(home_copy.get("seeAllCountriesLine", "See all 60 countries →")) + '</a></div>')


# Section 1, the ONE remaining country chart (Sebastian's 2026-09-28
# correction, item 2 merged the old demoted "10 widest gaps" chart into
# this one). Matches renderAllCountriesStrip() in index.html's own
# <script>. Every priced-or-median-eligible country gets a row (pegged
# included, lighter grey); layout order (item 3): the GAPS_TOP_N widest
# real gaps first, then a visible divider row, then Mexico and the
# Philippines pulled up regardless of their own rank (the two routes this
# site actually prices transfers on), then everyone else in the usual
# ranked order. Pegged rows no longer repeat their caption on every row --
# one legend line under the whole chart says it once.
ALL_LABEL_CCY = {"PHP": "transferPriced", "MXN": "transferPriced", "DZD": "noDollarsSold"}
GAPS_TOP_N = 10
PINNED_CCY = ("MXN", "PHP")
# Order Philippines before Mexico when the two are named together in a
# sentence ("In the Philippines and Mexico..."), matching the mockup's own
# phrasing order -- purely a sentence-building order, not the chart's own
# pin order above.
PINNED_PHRASE_ORDER = {"PHP": 0, "MXN": 1}
# How close to zero counts as "at the official rate" for the finding
# header/why paragraph -- looser than costPhrase()'s 0.05-point epsilon
# (index.html's own JS) because this is a plain-language finding about a
# whole country, not a per-hour sign check.
PAR_EPSILON = 0.15


def join_and(names):
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def find_pinned_at_par(rows_in):
    out = [c for c in rows_in if c.get("ccy") in PINNED_CCY and abs(c.get("gap_pct", 0.0)) < PAR_EPSILON]
    out.sort(key=lambda c: PINNED_PHRASE_ORDER.get(c.get("ccy"), 99))
    return out


def find_widest_managed(rows_in):
    managed = [c for c in rows_in if c.get("denominator_class") not in ("unmaintained", "pegged")]
    if not managed:
        return None
    return max(managed, key=lambda c: c.get("gap_pct", 0.0))


def country_finding_header_html(rows_in, home_copy):
    """Section C's h2 -- states the actual finding: which priced countries
    trade at the official rate, and by how much the widest real gap costs,
    both read live off data/index_latest.json, never typed (the mockup's
    "Algeria... 92%" is an example string in a design reference file, not a
    number this page may hardcode).
    """
    pinned = find_pinned_at_par(rows_in)
    widest = find_widest_managed(rows_in)
    parts = []
    if pinned:
        places = join_and([c.get("country", "") for c in pinned])
        parts.append(home_copy.get("countryFindingAtParTemplate", "").replace("{places}", places))
    if widest:
        parts.append(home_copy.get("countryFindingGapTemplate", "")
                      .replace("{country}", widest.get("country", ""))
                      .replace("{pct}", str(round(widest.get("gap_pct", 0.0)))))
    if not parts:
        return home_copy.get("countryFindingNoGapTemplate", "")
    return " ".join(parts)


def country_why_html(rows_in, home_copy, street_depth):
    """The "why" callout under the chart -- names the SAME pinned/widest
    countries the header above states, plus a real depth figure (data/
    street_depth_latest.json, tools/emit's own per-currency depth-of-book
    read) for the widest one, when that file has an entry for it.
    """
    pinned = find_pinned_at_par(rows_in)
    widest = find_widest_managed(rows_in)
    text = ""
    if pinned:
        places = join_and([c.get("country", "") for c in pinned])
        text += home_copy.get("countryWhyBothParTemplate", "").replace("{places}", places)
    if widest:
        depth = ((street_depth or {}).get("countries", {}) or {}).get(widest.get("ccy"), {})
        depth_usd = depth.get("depth_usd")
        threshold_pct = depth.get("threshold_pct")
        if depth_usd is not None and threshold_pct is not None:
            pct_words = str(int(threshold_pct)) if float(threshold_pct).is_integer() else str(threshold_pct)
            text += (home_copy.get("countryWhyGapTemplate", "")
                      .replace("{country}", widest.get("country", ""))
                      .replace("{amount}", "$" + f"{round(depth_usd):,}")
                      .replace("{pct}", pct_words))
        else:
            text += (home_copy.get("countryWhyGapNoDepthTemplate", "")
                      .replace("{country}", widest.get("country", "")))
    return text.strip()


def _ordered_rows(priced):
    """[(row_or_None_for_divider, is_divider)] in item 3's order: top
    GAPS_TOP_N non-pegged gaps, a divider, Mexico/Philippines (whichever of
    the two are actually priced this hour, in their own gap order). Sebastian's
    2026-09-28 follow-up to #211: the home chart shows only these rows now --
    everyone else stays on the-index.html, which the "All {n} priced
    countries ->" link already points to.
    """
    non_pegged = [c for c in priced if c.get("denominator_class") != "pegged"]
    top = non_pegged[:GAPS_TOP_N]
    top_ccys = {c.get("ccy") for c in top}
    pinned = [c for c in priced if c.get("ccy") in PINNED_CCY and c.get("ccy") not in top_ccys]
    out = [(c, False) for c in top]
    if top:
        out.append((None, True))
    out += [(c, False) for c in pinned]
    return out


def build_all_countries_strip(idx_doc, home_copy, dest_counts=None, street_depth=None):
    rows_in = _home_rows(idx_doc)
    priced = _priced_sorted(rows_in, exclude_pegged=False)
    if not priced:
        return None
    dest_counts = dest_counts or {}

    labels = home_copy.get("allCountriesLabels", {})
    W, row_h_plain, row_h_caption, row_h_div, top = PREMIUM_BAKE_W, 24, 38, 16, 6
    label_w = min(170, round(W * 0.42))
    value_w = min(60, round(W * 0.15))
    bar_left = label_w
    bar_right = W - value_w
    bar_w = bar_right - bar_left

    max_real = max(
        [c.get("gap_pct", 0.0) for c in priced if c.get("denominator_class") != "unmaintained"],
        default=1.0,
    ) or 1.0

    ordered = _ordered_rows(priced)

    # Every priced country gets a row; one with its own caption (Sudan, the
    # Philippines/Mexico) gets a taller row so the caption prints on its own
    # full-width line below the bar instead of being squeezed into the
    # narrow value column and clipped by the SVG's own viewBox
    # (SEB-reported). Pegged rows render lighter grey but carry no caption
    # of their own -- one legend line under the chart covers all of them.
    rows = []
    y = top
    n_priced = len(priced)
    for c, is_div in ordered:
        if is_div:
            row_y = y
            y += row_h_div
            rows.append(
                f'<line x1="0" y1="{row_y+8:.1f}" x2="{W}" y2="{row_y+8:.1f}" '
                f'stroke="#D3D0CB" stroke-width="1" stroke-dasharray="3,3"/>'
            )
            continue
        pct = c.get("gap_pct", 0.0)
        is_unmaintained = c.get("denominator_class") == "unmaintained"
        is_pegged = c.get("denominator_class") == "pegged"
        label_key = ALL_LABEL_CCY.get(c.get("ccy"))
        if is_unmaintained:
            caption = labels.get("frozenRate", "official rate frozen, not comparable")
        elif label_key == "transferPriced":
            n_sends = dest_counts.get(c.get("ccy"), 0)
            caption = labels.get("transferPricedTemplate", "").replace("{n}", str(n_sends))
        elif label_key:
            caption = labels.get(label_key, "")
        else:
            caption = ""
        row_y = y
        y += row_h_caption if caption else row_h_plain
        w = bar_w if is_unmaintained else max(2.0, min(1.0, pct / max_real) * bar_w)
        fill = "#EDEDED" if is_pegged else ("#D3D0CB" if is_unmaintained else "#9A9A9A")
        text_fill = "#9A9A9A" if (is_pegged or is_unmaintained) else "#0B0B0B"
        tip_rounded = round(pct, 2)
        tip = c.get("country", "") + ": " + ("+" if tip_rounded > 0 else "") + f"{abs(tip_rounded) if tip_rounded == 0 else tip_rounded:.2f}% vs the official rate, 24h median"
        href = "./country.html?ccy=" + esc(c.get("ccy", ""))
        rounded = round(pct, 1)
        sign = "+" if rounded > 0 else ""
        value_text = f"{sign}{abs(rounded) if rounded == 0 else rounded:.1f}%"
        country_label = c.get("country", "")
        if country_label.lower().startswith("the "):
            country_label = country_label[4:]
        break_mark = (
            f'<line x1="{bar_right-5}" y1="{row_y+2:.1f}" x2="{bar_right-1}" y2="{row_y+12:.1f}" stroke="#fff" stroke-width="2"/>'
            if is_unmaintained else ""
        )
        caption_svg = (
            f'<text x="0" y="{row_y+31:.1f}" font-family="Archivo,sans-serif" font-size="14" fill="#9A9A9A">{esc(caption)}</text>'
            if caption else ""
        )
        rows.append(
            f'<a href="{href}"><title>{esc(tip)}</title>'
            f'<text x="0" y="{row_y+16:.1f}" font-family="Archivo,sans-serif" font-size="14" font-weight="500" fill="{text_fill}">{esc(country_label)}</text>'
            f'<rect x="{bar_left}" y="{row_y+4:.1f}" width="{w:.1f}" height="10" rx="2" fill="{fill}"/>{break_mark}'
            f'<text x="{W-4}" y="{row_y+13:.1f}" text-anchor="end" font-family="ui-monospace,monospace" font-size="14" font-weight="500" fill="{text_fill}">{value_text}</text>'
            f'{caption_svg}</a>'
        )
    H = y + 10

    svg_html = (
        f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:800px;height:auto" class="strip-svg">'
        + "".join(rows)
        + '</svg>'
    )
    header = esc(country_finding_header_html(rows_in, home_copy))
    answer = esc(home_copy.get("allCountriesAnswerLine", ""))
    median_note = esc(home_copy.get("allCountriesMedianNote", "Median of the last 24 hours."))
    pegged_legend = esc(home_copy.get("allCountriesPeggedLegend",
        "Light grey: pegged currency, the gap is the cost of buying stablecoins."))
    note = esc(home_copy.get("allCountriesNote", ""))
    # Sebastian's 2026-09-28 final mockup, item 6: this one link drops the
    # live priced-count number ("All 51 priced countries →" -> "All
    # countries →") -- a simplification of THIS label only, not a general
    # ban on stating the count elsewhere on the site.
    link = esc(home_copy.get("allCountriesLinkTemplate", "All countries →"))
    why = esc(country_why_html(rows_in, home_copy, street_depth))
    return (
        "<h2>" + header + "</h2>"
        '<p class="answer">' + answer + "</p>"
        '<div class="strip-wrap">' + svg_html + '</div>'
        '<div class="strip-note">' + median_note + '</div>'
        '<div class="strip-note">' + pegged_legend + '</div>'
        '<div class="strip-note">' + note + '</div>'
        '<p class="plainline">' + why + '</p>'
        '<div class="strip-note"><a href="./the-index.html" style="font-weight:600;color:#0B0B0B">' + link + '</a></div>'
    )


def pct(bps):
    """A COST figure (waterfall legs, duel comparison). Sebastian's
    2026-09-28 correction: costs never carry a leading "+" -- "0.87%", not
    "+0.87%" -- the "+" convention belongs to GAP figures only (street price
    vs official rate), which is a different function (see index.html's own
    JS: costPhrase()/renderAllCountriesStrip() still sign gaps explicitly).
    """
    v = bps / 100.0
    return ("%.2f" % v) + "%"


def duel_html(corridors, home_copy, rung):
    """The duel comparison: two big numbers, live from the SAME
    corridor_summary.json data the waterfall reads -- never the mockup's
    literal "0.87% vs 0.46%". Leads on SGD->PHP; the small link below names
    every OTHER corridor where the cheapest app also beats the stablecoin,
    computed the same way as here, never a fixed list. Mirrors index.html's
    own renderDuel() JS exactly so the server bake and the client re-render
    can never disagree.

    The "cheapest app" figure is primary["baseline_cost_bps_median"] --
    the PUBLIC COMPARISON feed's (Wise's) typical/median-hour cost, the
    same figure data/corridor_window.json's own "best_cost" already uses
    (see build_window() above) and the same one this table used before a
    "richer" cheapest_app() lookup into data/providers_latest.json was
    added here. That lookup picked the single cheapest quote in
    providers_latest.json's CURRENT hour, direct provider quotes included
    -- a single-hour outlier from a provider like Airwallex or Instarem
    (a near-zero spot quote that is not available as a typical, repeatable
    price) then got reported as "the cheapest app," landing at 0.14% for
    Singapore->Philippines and 0.06% for New Zealand->Philippines instead
    of a real, typical figure near 0.46%. baseline_cost_bps_median is a
    median over the same measurement window the stablecoin figure uses, so
    the two numbers in this comparison are finally apples-to-apples: same
    "typical hour," same methodology, one public-comparison price against
    one exchange-measured price.
    """
    if not corridors:
        return None
    primary = next((c for c in corridors if c.get("corridor") == "SGD->PHP"), corridors[0])
    app_bps = primary.get("baseline_cost_bps_median")
    stable_bps = primary["taker_cost_bps_median"]
    src, _, dest_ccy = (primary.get("corridor") or "").partition("->")
    dest = DEST_NAME.get(dest_ccy, "")
    amount = SRC_SYMBOL.get(src, src + " ") + f"{round(rung):,}"
    caption = (home_copy.get("duelCaptionTemplate", "Sending {amount} from {src} to {dest}, all-in cost, typical hour.")
               .replace("{amount}", amount).replace("{src}", SRC_NAME.get(src, src)).replace("{dest}", dest))
    others = []
    for c in corridors:
        if c.get("corridor") == primary.get("corridor"):
            continue
        other_app_bps = c.get("baseline_cost_bps_median")
        if other_app_bps is not None and c["taker_cost_bps_median"] > other_app_bps:
            other_src = (c.get("corridor") or "").split("->")[0]
            others.append(SRC_NAME.get(other_src, other_src))
    if others:
        same_result = (home_copy.get("duelSameResultTemplate",
            'Same result from {others}. <a href="./sending-money.html">All routes and providers →</a>')
            .replace("{others}", esc(join_and(others))))
    else:
        same_result = ('<a href="./sending-money.html">'
                        + esc(home_copy.get("everyProviderLink", "All routes and providers →")) + "</a>")
    return (
        '<div class="duel">'
        '<div><div class="big p">' + pct(stable_bps) + '</div><div class="lab">'
        + esc(home_copy.get("duelLabelStable", "Stablecoin")) + "</div></div>"
        '<div class="vs">' + esc(home_copy.get("duelVs", "vs")) + "</div>"
        '<div><div class="big">' + (pct(app_bps) if app_bps is not None else "—") + '</div><div class="lab">'
        + esc(home_copy.get("duelLabelApp", "Cheapest app")) + "</div></div>"
        "</div>"
        '<p class="cap">' + esc(caption) + "</p>"
        '<p class="small-note">' + same_result + "</p>"
    )


def replace_by_marker(html, name, new_inner):
    """Replace whatever sits between <!--BAKE:START:name--> and
    <!--BAKE:END:name--> with new_inner, keeping the markers themselves in
    place for the next run.

    Not tag-matching: the content baked in here (the corridor table, in
    particular) contains its own nested <div>s, and an earlier version of
    this function matched up to the first closing tag of the SAME kind
    rather than the one that actually closed the target element -- fine on
    a first bake into an empty placeholder, silently truncating everything
    after the injected content's own first nested </div> on every bake
    after that. Comment markers can't nest or get confused with real
    markup, so they don't have that failure mode regardless of what HTML
    is injected between them.
    """
    pattern = re.compile(
        r'(<!--BAKE:START:' + re.escape(name) + r'-->)(.*?)(<!--BAKE:END:' + re.escape(name) + r'-->)',
        re.S)
    if not pattern.search(html):
        return html, False
    return pattern.sub(lambda m: m.group(1) + new_inner + m.group(3), html, count=1), True


def main():
    if not os.path.exists(SUMMARY):
        print("  no data/corridor_summary.json yet -- leaving index.html's baked content as-is")
        return
    with open(SUMMARY) as f:
        doc = json.load(f)
    if doc.get("status") != "ok" or not doc.get("corridors"):
        print("  corridor_summary.json has no measurable corridors this pass -- leaving prior bake in place")
        return

    with open(os.path.join(HERE, "copy.json")) as f:
        copy_doc = json.load(f)
    home_copy = copy_doc.get("home", {})

    window = build_window(doc)
    with open(WINDOW_OUT, "w") as f:
        json.dump(window, f, indent=2, sort_keys=True)
        f.write("\n")

    with open(INDEX_HTML) as f:
        html = f.read()

    changed = False
    html, ok1 = replace_by_marker(html, "heroHeadline", esc(home_copy.get(
        "headline", "Sending money by stablecoin usually costs more than a transfer app")))
    changed = changed or ok1

    n_countries = count_countries()
    html, ok2 = replace_by_marker(html, "heroSub", sub_html(home_copy, n_countries))
    changed = changed or ok2

    rung = doc.get("rung", 5000)

    duel = duel_html(doc["corridors"], home_copy, rung)
    if duel is not None:
        html, ok3a = replace_by_marker(html, "duelSection", duel)
        changed = changed or ok3a

    idx_doc = load_index_latest()
    # Sebastian's 2026-09-28 correction, item 2: the second chart is gone --
    # this marker now holds a single static link line, not a data-driven
    # chart, so it bakes unconditionally rather than skipping when
    # index_latest.json is missing.
    html, ok4 = replace_by_marker(html, "premiumStrip", see_all_countries_line(home_copy))
    changed = changed or ok4

    # How many of the tracked sends actually land in each destination
    # currency ("where {n} of the transfers we price land here") -- read
    # from the SAME corridor list the table above renders, never a typed
    # count.
    dest_counts = {}
    for c in doc["corridors"]:
        dest_ccy = (c.get("corridor") or "").split("->")[-1]
        if dest_ccy:
            dest_counts[dest_ccy] = dest_counts.get(dest_ccy, 0) + 1
    street_depth = load_json_or_none(STREET_DEPTH_LATEST)

    all_strip = build_all_countries_strip(idx_doc, home_copy, dest_counts, street_depth)
    if all_strip is not None:
        html, ok5 = replace_by_marker(html, "allCountriesStrip", all_strip)
        changed = changed or ok5
    else:
        print("  no data/index_latest.json countries yet -- leaving all-countries chart's prior bake in place")

    if not changed:
        print("  WARNING: none of the expected id= anchors were found in index.html -- "
              "the page structure moved and this script needs updating, not silently skipped")
        sys.exit(1)

    with open(INDEX_HTML, "w") as f:
        f.write(html)
    print("  baked headline + duel comparison into index.html from data/corridor_summary.json")
    print(f"  wrote data/corridor_window.json ({len(window)} corridors)")


if __name__ == "__main__":
    main()
