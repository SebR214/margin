#!/usr/bin/env python3
"""D1 (v1 freeze and ship brief): bake the real headline and corridor table
into index.html's own markup at collection time, so a crawler or a visitor
with JS off sees the actual measurement -- not "Loading this hour's
measurement...", which is what ships otherwise.

Runs AFTER tools/emit_corridor_summary.py, every pass. Idempotent: each run
replaces exactly what the LAST run wrote, using the same id="..." anchors
the client-side JS already targets, so baking twice in a row (or baking
then letting JS re-render on load) never duplicates or drifts. The waterfall
CHART stays client-rendered -- an SVG bar chart is worth building in one
place (the browser, where MarginChart-style code already exists), not
twice.

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

# Plain currency symbols for the four routes this site prices at this
# level of detail. Labels only, never a number -- same rule as every other
# display map on this site (tools/emit_countries.py's COUNTRY, for one).
SRC_SYMBOL = {"SGD": "S$", "AUD": "A$", "NZD": "NZ$", "USD": "US$"}

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


def _ordered_rows(priced):
    """[(row_or_None_for_divider, is_divider)] in item 3's order: top
    GAPS_TOP_N non-pegged gaps, a divider, Mexico/Philippines (whichever of
    the two are actually priced this hour, in their own gap order), then
    the rest -- each real country appearing exactly once.
    """
    non_pegged = [c for c in priced if c.get("denominator_class") != "pegged"]
    top = non_pegged[:GAPS_TOP_N]
    top_ccys = {c.get("ccy") for c in top}
    pinned = [c for c in priced if c.get("ccy") in PINNED_CCY and c.get("ccy") not in top_ccys]
    pinned_ccys = {c.get("ccy") for c in pinned}
    rest = [c for c in priced if c.get("ccy") not in top_ccys and c.get("ccy") not in pinned_ccys]
    out = [(c, False) for c in top]
    if top:
        out.append((None, True))
    out += [(c, False) for c in pinned]
    out += [(c, False) for c in rest]
    return out


def build_all_countries_strip(idx_doc, home_copy):
    rows_in = _home_rows(idx_doc)
    priced = _priced_sorted(rows_in, exclude_pegged=False)
    if not priced:
        return None

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
        elif label_key:
            caption = labels.get(label_key, "")
        else:
            caption = ""
        row_y = y
        y += row_h_caption if caption else row_h_plain
        w = bar_w if is_unmaintained else max(2.0, min(1.0, pct / max_real) * bar_w)
        fill = "#EDEDED" if is_pegged else ("#D3D0CB" if is_unmaintained else "#9A9A9A")
        text_fill = "#9A9A9A" if (is_pegged or is_unmaintained) else "#0B0B0B"
        tip = c.get("country", "") + ": " + ("+" if pct >= 0 else "") + f"{pct:.2f}% vs the official rate, 24h median"
        href = "./country.html?ccy=" + esc(c.get("ccy", ""))
        sign = "+" if pct >= 0 else ""
        value_text = f"{sign}{pct:.1f}%"
        break_mark = (
            f'<line x1="{bar_right-5}" y1="{row_y+2:.1f}" x2="{bar_right-1}" y2="{row_y+12:.1f}" stroke="#fff" stroke-width="2"/>'
            if is_unmaintained else ""
        )
        caption_svg = (
            f'<text x="0" y="{row_y+30:.1f}" font-family="Archivo,sans-serif" font-size="10" fill="#9A9A9A">{esc(caption)}</text>'
            if caption else ""
        )
        rows.append(
            f'<a href="{href}"><title>{esc(tip)}</title>'
            f'<text x="0" y="{row_y+16:.1f}" font-family="Archivo,sans-serif" font-size="12" font-weight="500" fill="{text_fill}">{esc(c.get("country", ""))}</text>'
            f'<rect x="{bar_left}" y="{row_y+4:.1f}" width="{w:.1f}" height="10" rx="2" fill="{fill}"/>{break_mark}'
            f'<text x="{W-4}" y="{row_y+13:.1f}" text-anchor="end" font-family="ui-monospace,monospace" font-size="11" font-weight="500" fill="{text_fill}">{value_text}</text>'
            f'{caption_svg}</a>'
        )
    H = y + 10

    svg_html = (
        f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:800px;height:auto" class="strip-svg">'
        + "".join(rows)
        + '</svg>'
    )
    title = esc(home_copy.get("allCountriesTitle", "What a dollar costs on the street vs the official rate, every country we track"))
    median_note = esc(home_copy.get("allCountriesMedianNote", "Median of the last 24 hours."))
    pegged_legend = esc(home_copy.get("allCountriesPeggedLegend",
        "Light grey: pegged currency, the gap is the cost of buying stablecoins."))
    note = esc(home_copy.get("allCountriesNote", ""))
    link = esc(home_copy.get("allCountriesLinkTemplate", "All {n} priced countries →")
               .replace("{n}", str(n_priced)))
    return (
        '<div class="waterfall-title">' + title + '</div>'
        '<div class="strip-wrap">' + svg_html + '</div>'
        '<div class="strip-note">' + median_note + '</div>'
        '<div class="strip-note">' + pegged_legend + '</div>'
        '<div class="strip-note">' + note + '</div>'
        '<div class="strip-note"><a href="./the-index.html" style="font-weight:600;color:#0B0B0B">' + link + '</a></div>'
    )


def win_cell_html(c):
    """The win-rate cell. Always states the market-order (taker) win rate --
    the real, almost-always-zero result -- and adds the limit-order (maker)
    rate as a second line only where it clears 10%, so a route where
    waiting for your own price genuinely changes the answer (USD->MXN)
    still shows both numbers, at equal visual weight, instead of one
    hiding the other.
    """
    t, m = c["win_rate_taker_pct"], c["win_rate_maker_pct"]
    html = '<div class="' + ("win-yes" if t >= 10 else "win-no") + '">' + ("%.1f" % t) + "% (market order)</div>"
    if m >= 10:
        html += '<div class="win-yes" style="margin-top:4px">' + ("%.1f" % m) + "% (limit order)</div>"
    return html


def pct(bps):
    """A COST figure (waterfall legs, corridor table cells). Sebastian's
    2026-09-28 correction: costs never carry a leading "+" -- "0.87%", not
    "+0.87%" -- the "+" convention belongs to GAP figures only (street price
    vs official rate), which is a different function (see index.html's own
    JS: costPhrase()/renderAllCountriesStrip() still sign gaps explicitly).
    """
    v = bps / 100.0
    return ("%.2f" % v) + "%"


# Sebastian's 2026-09-28 correction, item 4: the home page's corridor table
# uses arrow notation for its route labels ("Singapore → Philippines"), not
# the "Singapore to the Philippines" phrasing data/providers_latest.json's
# own route_words carries for every other page. Display-only, local to this
# page's render -- the shared route_words value itself is untouched so
# corridor.html and fee-tiers.html keep their existing wording.
ARROW_ROUTE_WORDS = {
    "SGD->PHP": "Singapore → Philippines",
    "AUD->PHP": "Australia → Philippines",
    "NZD->PHP": "New Zealand → Philippines",
    "USD->MXN": "US → Mexico",
}


def corridor_row_html(c, home_copy, window):
    """One corridor row, with its own window ("typical, N hours since D
    Mon YYYY") printed right under the route name -- Day 1's window-label
    rule: a reader should never have to guess which window a number on this
    table covers, and every corridor gets its own real label instead of the
    page stating one window (SGD->PHP's, in the waterfall above) and
    letting the reader assume every other row shares it. Read from
    data/corridor_window.json, the one file this figure is written to, so
    the label can never say a different window than the number itself.
    """
    row = (window or {}).get(c.get("corridor"), {})
    win_note = ""
    win_text = row.get("window")
    if win_text:
        win_note = '<div style="font-size:11px;color:#9A9A9A;font-weight:400">' + esc(win_text) + "</div>"
    label = ARROW_ROUTE_WORDS.get(c.get("corridor"), c.get("route_words", c["corridor"]))
    return (
        "<tr>"
        "<td><b>" + esc(label) + "</b>" + win_note + "</td>"
        '<td class="num">' + pct(c["taker_cost_bps_median"]) + "</td>"
        '<td class="num">' + pct(c["baseline_cost_bps_median"]) + "</td>"
        "<td>" + win_cell_html(c) + "</td>"
        '<td><a href="./corridor.html?corridor=' + esc(c["corridor"]) + '" style="font-weight:600;color:#0B0B0B">'
        + esc(home_copy.get("seeCorridor", "see the receipt →")) + "</a></td>"
        "</tr>"
    )


def corridor_table_html(corridors, home_copy, window):
    cols = home_copy.get("corridorTableCols", {})
    rows = "".join(corridor_row_html(c, home_copy, window) for c in corridors)
    mxn = next((c for c in corridors if c.get("corridor") == "USD->MXN"), None)
    first_line = (home_copy.get("corridorTableFirstLine", "")
                  .replace("{maker_pct}", ("%.1f" % mxn["win_rate_maker_pct"]) if mxn else ""))
    return (
        '<div class="waterfall-title">' + esc(home_copy.get("corridorTableTitle", "Stablecoin route vs cheapest app, all-in cost per route")) + "</div>"
        '<div class="lede">' + esc(first_line) + "</div>"
        '<table class="corridor-table"><thead><tr>'
        "<th>" + esc(cols.get("corridor", "ROUTE")) + "</th>"
        "<th>" + esc(cols.get("stablecoin", "STABLECOIN ROUTE")) + "</th>"
        "<th>" + esc(cols.get("fiat", "CHEAPEST APP")) + "</th>"
        "<th>" + esc(cols.get("winRate", "HOURS STABLECOIN WAS CHEAPER")) + "</th>"
        "<th></th></tr></thead><tbody>" + rows + "</tbody></table>"
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
        "headline", "Stablecoins rarely beat the cheapest transfer app. But where banks won't sell you dollars, they're how people get one.")))
    changed = changed or ok1

    n_countries = count_countries()
    html, ok2 = replace_by_marker(html, "heroSub", sub_html(home_copy, n_countries))
    changed = changed or ok2

    table = corridor_table_html(doc["corridors"], home_copy, window)
    html, ok3 = replace_by_marker(html, "corridorTableSection", table)
    changed = changed or ok3

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
    print("  baked headline + corridor table into index.html from data/corridor_summary.json")
    print(f"  wrote data/corridor_window.json ({len(window)} corridors)")


if __name__ == "__main__":
    main()
