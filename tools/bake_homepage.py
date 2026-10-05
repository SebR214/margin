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

import emit_receipts

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY = os.path.join(HERE, "data", "corridor_summary.json")
SAMPLES = os.path.join(HERE, "data", "samples.csv")
WINDOW_OUT = os.path.join(HERE, "data", "corridor_window.json")
INDEX_HTML = os.path.join(HERE, "index.html")
INDEX_LATEST = os.path.join(HERE, "data", "index_latest.json")
RECEIPTS_DIR = os.path.join(HERE, "data", "receipts")


def load_receipt(ccy):
    """data/receipts/<CCY>.json, or None if emit_receipts.py hasn't run yet
    this pass -- a missing receipt means no no-JS fallback for that row, not
    a guessed-at one (SEB-173)."""
    path = os.path.join(RECEIPTS_DIR, f"{ccy}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


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


def sub_html(home_copy, n_countries, n_corridors=None):
    """The plain, fixed sub sentence (copy.json home.headlineSub), with its
    two real counts -- how many corridors are tracked, and how many
    countries we price a street dollar in -- filled in live from
    data/corridor_summary.json and data/index_latest.json, never typed.
    "4 corridors" sat hardcoded in copy.json's own template until the
    2026-09-29 SOURCES-2 batch took the real count to 7 and the sentence
    went stale the moment it shipped -- {n_corridors} closes that the same
    way {n_countries} already worked. The sentence itself carries a real
    <a> to how-it-works.html, so this is NOT html-escaped as a whole (only
    the numeric substitutions would need it, and a plain digit string never
    needs escaping).
    """
    tmpl = home_copy.get("headlineSub", "")
    tmpl = tmpl.replace("{n_countries}", str(n_countries) if n_countries is not None else "")
    return tmpl.replace("{n_corridors}", str(n_corridors) if n_corridors is not None else "")


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
    ones; "withheld" is counted separately), the same file countries.html
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
    return ""



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
# The header states "at the official rate" precisely (PAR_EPSILON above);
# the why-sentence below makes a broader, structural claim about these two
# corridors -- a normal app already gets a fair rate there, so a stablecoin
# has nothing to beat -- not a per-hour sign check, so it uses countries.
# html's own "near official rate" threshold (SMALL_GAP=2) instead. Tying it
# to the header's tighter epsilon meant an ordinary hour where a pinned
# country's gap ticked from 0.14% to 0.17% silently deleted the one
# sentence connecting the two halves of the home page (SEB, 2026-09-29).
PAR_EPSILON_WHY = 2.0


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


def find_pinned_near_par(rows_in):
    out = [c for c in rows_in if c.get("ccy") in PINNED_CCY and abs(c.get("gap_pct", 0.0)) < PAR_EPSILON_WHY]
    out.sort(key=lambda c: PINNED_PHRASE_ORDER.get(c.get("ccy"), 99))
    return out


def find_widest_managed(rows_in):
    managed = [c for c in rows_in if c.get("denominator_class") not in ("unmaintained", "pegged")]
    if not managed:
        return None
    return max(managed, key=lambda c: c.get("gap_pct", 0.0))


def fmt_rate(v):
    """A price per dollar for a sentence: one decimal from 100 up, two from 1
    up, four below that. Mirrors fmtRate() in index.html's own script."""
    digits = 1 if v >= 100 else (2 if v >= 1 else 4)
    return f"{v:,.{digits}f}"


def has_gap(widest):
    """A gap that rounds to 0% is not "people pay 0% more". Mirrors
    index.html's hasGap check."""
    return bool(widest) and round(widest.get("gap_pct", 0.0)) >= 1


def country_finding_header_html(rows_in, home_copy):
    """Section C's h2 -- states the finding for the widest real gap, read
    live off data/index_latest.json, never typed (SEB-221: "In {country}
    people pay {pct}% more for a dollar than the official rate").
    """
    widest = find_widest_managed(rows_in)
    if not has_gap(widest):
        return home_copy.get("countryFindingNoGapTemplate", "")
    return (home_copy.get("countryFindingGapTemplate", "")
            .replace("{country}", widest.get("country", ""))
            .replace("{pct}", str(round(widest.get("gap_pct", 0.0)))))


def country_explain_html(rows_in, home_copy):
    """The paragraph under the heading. Wording is chosen by the widest
    country's own denominator_class (copy.json home.countryExplainByClass),
    never written for one named country. Street price and official rate are
    data/countries/<CCY>.json's buy_price and fx_mid_per_usd. Mirrors
    countryExplain() in index.html's own script.
    """
    widest = find_widest_managed(rows_in)
    if not has_gap(widest):
        return ""
    cdoc = load_json_or_none(os.path.join(HERE, "data", "countries", f"{widest.get('ccy')}.json")) or {}
    if cdoc.get("buy_price") is None or cdoc.get("fx_mid_per_usd") is None:
        return home_copy.get("countryExplainNoPriceTemplate", "").replace("{country}", widest.get("country", ""))
    # Same 24 hour median gap as the heading, applied to the official rate.
    street = cdoc["fx_mid_per_usd"] * (1 + widest.get("gap_pct", 0.0) / 100)
    by_class = home_copy.get("countryExplainByClass", {})
    tpl = by_class.get(widest.get("denominator_class")) or by_class.get("default", "")
    first = (tpl.replace("{country}", widest.get("country", ""))
                .replace("{currency}", widest.get("ccy", ""))
                .replace("{street_price}", fmt_rate(street))
                .replace("{official_rate}", fmt_rate(cdoc["fx_mid_per_usd"])))
    second = (home_copy.get("countryConsequenceTemplate", "")
              .replace("{currency}", widest.get("ccy", ""))
              .replace("{street_100}", f"{round(float(fmt_rate(street).replace(',', '')) * 100):,}")
              .replace("{official_100}", f"{round(float(fmt_rate(cdoc['fx_mid_per_usd']).replace(',', '')) * 100):,}"))
    return first + " " + second


def country_close_html(rows_in, home_copy):
    """The closing line: names whichever of the Philippines and Mexico sit
    near the official rate this hour, read from the data, never typed."""
    pinned = find_pinned_near_par(rows_in)
    if not pinned:
        return ""
    places = join_and([c.get("country", "") for c in pinned])
    out = home_copy.get("countryCloseTemplate", "").replace("{places}", places)
    return out


def _ordered_rows(priced):
    """[(row_or_None_for_divider, is_divider)] in item 3's order: top
    GAPS_TOP_N non-pegged gaps, a divider, Mexico/Philippines (whichever of
    the two are actually priced this hour, in their own gap order). Sebastian's
    2026-09-28 follow-up to #211: the home chart shows only these rows now --
    everyone else stays on countries.html, which the "All {n} priced
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


def build_all_countries_strip(idx_doc, home_copy):
    """Home's country section, matching docs/mockups/home.html: the finding
    as the heading, one answer line, the 5 widest managed-rate gaps as bars,
    then the Philippines and Mexico (where our routes land), one sentence,
    one link. Sudan (frozen rate) and pegged currencies are left out here,
    they stay on countries.html. index.html's own script renders the same
    markup client-side (renderAllCountriesStrip) -- keep the two in sync.
    """
    rows_in = _home_rows(idx_doc)
    priced = _priced_sorted(rows_in, exclude_pegged=False)
    if not priced:
        return None
    top = [c for c in priced if c.get("denominator_class") not in ("pegged", "unmaintained")][:5]
    by_ccy = {c.get("ccy"): c for c in priced}
    pins = [by_ccy[k] for k in ("PHP", "MXN") if k in by_ccy]
    mx = max([c.get("gap_pct", 0.0) for c in top] or [1.0]) or 1.0

    def name(c):
        n = c.get("country", "")
        return n[4:] if n.lower().startswith("the ") else n

    def pct_words(v):
        r = round(v)
        return f"{abs(r) if r == 0 else r}%"

    # Every gap number here is a receipt's own result_pct (SEB-173): the
    # <b> that shows it gets the same data-receipt-ccy/value attributes
    # js/receipt_replay.js listens for, clickable once JS runs. A no-JS
    # reader gets the identical four steps instead, from the receipt file
    # already on disk by the time this bakes (emit_receipts.py runs first
    # in collect.yml) -- never a second, guessed-at description.
    def receipt_attrs(ccy, display_value):
        return ' data-receipt-ccy="' + esc(ccy) + '" data-receipt-value="' + esc(display_value) + '" tabindex="0"'

    def receipt_fallback(ccy):
        receipt = load_receipt(ccy)
        return emit_receipts.render_noscript(receipt) if receipt else ""

    rows = ""
    for c in top:
        w = max(0.005, min(1.0, c.get("gap_pct", 0.0) / mx)) * 85
        ccy = c.get("ccy", "")
        value = pct_words(c.get("gap_pct", 0.0))
        rows += ('<a class="crow" href="./country.html?ccy=' + esc(ccy) + '">'
                 '<span class="cname">' + esc(name(c)) + '</span>'
                 '<span class="cbar"><i style="width:' + f"{w:.1f}" + '%"></i>'
                 '<b style="left:' + f"{w:.1f}" + '%"' + receipt_attrs(ccy, value) + '>' + value + '</b></span></a>'
                 + receipt_fallback(ccy))
    pin_rows = ""
    for c in pins:
        ccy = c.get("ccy", "")
        value = pct_words(c.get("gap_pct", 0.0))
        pin_rows += ('<a class="crow low" href="./country.html?ccy=' + esc(ccy) + '">'
                     '<span class="cname">' + esc(name(c)) + '</span>'
                     '<span class="cbar"><i style="width:0"></i><b style="left:0"' + receipt_attrs(ccy, value) + '>'
                     + value + '</b></span></a>'
                     + receipt_fallback(ccy))
    header = esc(country_finding_header_html(rows_in, home_copy))
    explain = esc(country_explain_html(rows_in, home_copy))
    closing = esc(country_close_html(rows_in, home_copy))
    return ('<h2>' + header + '</h2>'
            + ('<p class="answer">' + explain + '</p>' if explain else '')
            + '<div class="cbars">' + rows + '<div class="cgap"></div>' + pin_rows + '</div>'
            + ('<p class="plainline">' + closing + '</p>' if closing else '')
            + '<p class="small-note"><a href="./countries.html">All countries →</a></p>')


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
    cap_tpl = home_copy.get("duelCaptionTemplate", "") if app_bps is not None else home_copy.get("duelCaptionNoAppTemplate", "")
    caption = (cap_tpl.replace("{amount}", amount).replace("{origin}", SRC_NAME.get(src, src))
               .replace("{destination}", dest).replace("{app_cost}", pct(app_bps) if app_bps is not None else "")
               .replace("{stable_cost}", pct(stable_bps)))
    sym = SRC_SYMBOL.get(src, src + " ")
    if app_bps is not None:
        caption += " " + (home_copy.get("duelMoneyTemplate", "")
                          .replace("{app_money}", money(rung * app_bps / 10000, sym))
                          .replace("{stable_money}", money(rung * stable_bps / 10000, sym)))
    caption += " " + home_copy.get("duelStablecoinNote", "")
    others = []
    for c in corridors:
        if c.get("corridor") == primary.get("corridor"):
            continue
        other_app_bps = c.get("baseline_cost_bps_median")
        if other_app_bps is not None and c["taker_cost_bps_median"] > other_app_bps:
            other_src = (c.get("corridor") or "").split("->")[0]
            others.append(c.get("route_words") or SRC_NAME.get(other_src, other_src))
    if others:
        same_result = (home_copy.get("duelSameResultTemplate", "")
            .replace("{routes}", esc(join_and(others))))
    else:
        same_result = ('<a href="./sending-money.html">'
                        + esc(home_copy.get("everyProviderLink", "")) + "</a>")
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

    # SEB-240: the home page is rebuilt in the browser from stored files and
    # carries no BAKE markers. Nothing to bake into it; data/corridor_window.json
    # (written above, read by other pages) is still this tool's job.
    if "<!--BAKE:START:" not in html:
        print("  index.html has no BAKE markers (home reads stored files in the browser) -- nothing to bake")
        print(f"  wrote data/corridor_window.json ({len(window)} corridors)")
        return

    changed = False
    html, ok1 = replace_by_marker(html, "heroHeadline", esc(home_copy.get(
        "headline", "Sending money by stablecoin usually costs more than a transfer app")))
    changed = changed or ok1

    n_countries = (len((idx_doc_for_sub := load_index_latest() or {}).get("countries") or []) + len(idx_doc_for_sub.get("withheld") or [])) or None
    n_corridors = len(doc["corridors"]) or None
    html, ok2 = replace_by_marker(html, "heroSub", sub_html(home_copy, n_countries, n_corridors))
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

    all_strip = build_all_countries_strip(idx_doc, home_copy)
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
