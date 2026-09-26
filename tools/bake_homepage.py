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
        if since and n:
            row["window"] = f"the typical cost over the {n:,} hours we've checked since {fmt_date(since)}"
        elif n:
            row["window"] = f"the typical cost over the {n:,} hours we've checked"
        else:
            row["window"] = "the typical cost across every hour we've checked"
        out[corridor] = row
    return out


def sub_html(home_copy, n_routes, n_countries):
    """The plain, fixed sub sentence (copy.json home.headlineSub), with its
    two real counts -- how many routes we price sending money on, how many
    countries we price a street dollar in -- filled in live from
    data/corridor_summary.json and data/index_latest.json, never typed.
    """
    tmpl = home_copy.get("headlineSub", "")
    vals = {
        "n_routes": str(n_routes) if n_routes is not None else "",
        "n_countries": str(n_countries) if n_countries is not None else "",
    }
    out = tmpl
    for k, v in vals.items():
        out = out.replace("{" + k + "}", esc(v))
    return out


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


# Phase 3: "Where the line runs" -- a single horizontal strip of every
# tracked country, positioned by its own real index_pct (street-dollar
# premium over the official rate), from "official rate is real" (0, left)
# to "official rate is fiction" (a log1p scale, right). Built ONLY from
# data/index_latest.json -- no new data collection, additive-only per
# VISION.md.
#
# x-position: index_pct clamped to [0, PREMIUM_CAP] then log1p-scaled, so
# the many countries clustered near 0% (PHP, MXN, IDR, ...) actually
# separate visually instead of collapsing into one pixel, while a genuine
# outlier (Sudan's frozen, unmaintained peg -- 1000%+ some hours) clamps to
# the right edge rather than compressing every other country into the
# leftmost 10% of the strip.
PREMIUM_CAP = 100.0


def _premium_xfrac(pct):
    v = max(pct, 0.0)
    v = min(v, PREMIUM_CAP)
    return math.log1p(v) / math.log1p(PREMIUM_CAP)


# Label collision avoidance: a plain beeswarm. Countries are sorted by
# their real x-position, then each is placed in the first lane (a stacked
# row above the axis) whose last-placed label doesn't overlap this one --
# never a fixed/hand-picked lane per country, so the layout self-adjusts
# as the real numbers (and which countries cluster where) change hour to
# hour.
_LABEL_HALF_W = 15
_LANE_H = 13
_MIN_GAP = 4
# The left edge of a log-scaled strip is where most countries land -- near-
# zero gaps barely separate on this axis, so lane-packing stacked a dozen-
# deep tower of 3-letter codes there. A first pass capped the tower at 5
# rows; still a block of touching labels, not actually fixed (SEB,
# 2026-09-26: "doesn't seem like you fixed anything"). Single row only -- a
# label prints when it clears the previous KEPT label, exactly what "lane
# 0" already means in _pack_lanes. Everything else stays a plain dot on the
# axis with its leader line and hover tooltip; the chart's one deliberate
# outlier (the biggest gap) always keeps its label regardless of lane.
_MAX_LABEL_LANE = 0


def _pack_lanes(points):
    lanes = []  # last right-edge (in x units) claimed in each lane
    for p in points:
        lane = 0
        while lane < len(lanes) and lanes[lane] + _MIN_GAP > (p["x"] - _LABEL_HALF_W):
            lane += 1
        if lane == len(lanes):
            lanes.append(0.0)
        lanes[lane] = p["x"] + _LABEL_HALF_W
        p["lane"] = lane
    return points


def build_premium_strip(idx_doc, home_copy):
    """The inner HTML for the premium-strip section: title, the SVG strip
    itself (axis + one marker per tracked country, each linking to
    country.html?ccy=X), and the three-sentence note with the real
    biggest-gap country and percentage filled in live.

    "Biggest gap" uses the same rule as the-index.html's own featured-
    country pick (denominator_class != "unmaintained") -- a frozen,
    unmaintained peg's huge nominal gap is an artifact of the peg, not a
    real market read, so it's shown on the strip (still a real, tracked
    country) but never the sentence's own headline number.
    """
    if idx_doc is None:
        return None
    countries = idx_doc.get("countries") or []
    if not countries:
        return None

    managed = [c for c in countries if c.get("denominator_class") != "unmaintained"]
    pool = managed if managed else countries
    biggest = max(pool, key=lambda c: c.get("index_pct", 0.0))
    hour = (idx_doc.get("as_of_utc") or idx_doc.get("computed_at") or "")[11:16]

    W = 800
    ML, MR = 16, 16
    PW = W - ML - MR
    TOP_PAD = 16
    BOTTOM_H = 40

    pts = []
    for c in countries:
        pct = c.get("index_pct")
        if pct is None:
            continue
        pts.append({"c": c, "x": ML + _premium_xfrac(pct) * PW})
    pts.sort(key=lambda p: p["x"])
    _pack_lanes(pts)

    biggest_ccy = biggest.get("ccy")
    max_lane = max(
        (p["lane"] if p["c"].get("ccy") == biggest_ccy else min(p["lane"], _MAX_LABEL_LANE) for p in pts),
        default=0,
    )
    axis_y = TOP_PAD + (max_lane + 1) * _LANE_H + 10
    h = axis_y + BOTTOM_H
    thresh_x = ML + _premium_xfrac(10.0) * PW

    svg = []
    svg.append(f'<line x1="{ML:.1f}" y1="{axis_y:.1f}" x2="{ML+PW:.1f}" y2="{axis_y:.1f}" stroke="#E5E5EA" stroke-width="1"/>')
    svg.append(f'<line x1="{thresh_x:.1f}" y1="{axis_y-6:.1f}" x2="{thresh_x:.1f}" y2="{axis_y+6:.1f}" stroke="#9A9A9A" stroke-width="1" stroke-dasharray="4,3"/>')
    svg.append(f'<text x="{thresh_x:.1f}" y="{axis_y+20:.1f}" font-family="Archivo,sans-serif" font-size="10.5" fill="#9A9A9A" text-anchor="middle">10%</text>')
    svg.append(f'<text x="{ML:.1f}" y="{axis_y+34:.1f}" font-family="Archivo,sans-serif" font-size="12" fill="#6B6B6B">' + esc(home_copy.get("premiumStripAxisLeft", "official rate is real")) + '</text>')
    svg.append(f'<text x="{ML+PW:.1f}" y="{axis_y+34:.1f}" font-family="Archivo,sans-serif" font-size="12" fill="#6B6B6B" text-anchor="end">' + esc(home_copy.get("premiumStripAxisRight", "official rate is fiction (log scale above 10%)")) + '</text>')

    for p in pts:
        c, x, lane = p["c"], p["x"], p["lane"]
        is_big = c.get("ccy") == biggest_ccy
        labeled = is_big or lane <= _MAX_LABEL_LANE
        label_y = axis_y - 10 - min(lane, _MAX_LABEL_LANE) * _LANE_H
        is_unmaintained = c.get("denominator_class") == "unmaintained"
        r = 5 if is_big else 3
        fill = "#3F3047" if is_big else ("#D3D0CB" if is_unmaintained else "#817FCC")
        text_fill = "#3F3047" if is_big else ("#9A9A9A" if is_unmaintained else "#0B0B0B")
        weight = "700" if is_big else "500"
        pct = c.get("index_pct", 0.0)
        tip = c.get("country", "") + ": " + ("+" if pct >= 0 else "") + f"{pct:.2f}% vs the official rate"
        href = "./country.html?ccy=" + esc(c.get("ccy", ""))
        piece = ['<a href="' + href + '">', '<title>' + esc(tip) + '</title>']
        if labeled and lane > 0:
            piece.append(f'<line x1="{x:.1f}" y1="{axis_y-3:.1f}" x2="{x:.1f}" y2="{label_y+3:.1f}" stroke="#E5E5EA" stroke-width="1"/>')
        piece.append(f'<circle cx="{x:.1f}" cy="{axis_y:.1f}" r="{r}" fill="{fill}"/>')
        if labeled:
            piece.append(f'<text x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle" font-family="Archivo,sans-serif" font-size="9.5" font-weight="{weight}" fill="{text_fill}">' + esc(c.get("ccy", "")) + '</text>')
        piece.append('</a>')
        svg.append("".join(piece))

    svg_html = f'<svg viewBox="0 0 {W} {h}" style="width:100%;max-width:800px;height:auto" class="strip-svg">' + "".join(svg) + '</svg>'

    note_tmpl = home_copy.get("premiumStripNote", "")
    note = (note_tmpl
            .replace("{biggest_gap_country}", esc(biggest.get("country", "")))
            .replace("{biggest_gap_pct}", f"{biggest.get('index_pct', 0.0):.1f}%")
            .replace("{hour}", esc(hour)))

    title = esc(home_copy.get("premiumStripTitle", "Where the line runs"))
    return ('<div class="waterfall-title">' + title + '</div>'
            '<div class="strip-wrap">' + svg_html + '</div>'
            '<div class="strip-note">' + note + '</div>')


def win_cell_html(c):
    """The win-rate cell. When taker and maker execution genuinely diverge --
    USD->MXN's whole story, where a near-zero taker win rate hides a ~44%
    maker one -- both numbers are shown, at equal visual weight (colored,
    not a muted footnote), not one buried under the other. A 5-point gap is
    the data-driven test, not a hardcoded corridor name, so any future
    corridor with the same shape gets the same honest treatment.
    """
    t, m = c["win_rate_taker_pct"], c["win_rate_maker_pct"]
    if abs(t - m) >= 5:
        return (
            '<div class="' + ("win-yes" if t >= 10 else "win-no") + '">'
            + ("%.1f" % t) + "% of hours buying it now</div>"
            '<div class="' + ("win-yes" if m >= 10 else "win-no") + '" style="margin-top:4px">'
            + ("%.1f" % m) + "% of hours waiting for your price</div>"
        )
    return '<span class="' + ("win-yes" if t >= 10 else "win-no") + '">' + ("%.1f" % t) + "% of hours</span>"


def pct(bps):
    v = bps / 100.0
    return ("+" if v >= 0 else "") + ("%.2f" % v) + "%"


def corridor_row_html(c, home_copy):
    return (
        "<tr>"
        "<td><b>" + esc(c.get("route_words", c["corridor"])) + "</b></td>"
        '<td class="num">' + pct(c["taker_cost_bps_median"]) + "</td>"
        '<td class="num">' + pct(c["baseline_cost_bps_median"]) + "</td>"
        "<td>" + win_cell_html(c) + "</td>"
        '<td><a href="./corridor.html?corridor=' + esc(c["corridor"]) + '" style="font-weight:600;color:#0B0B0B">'
        + esc(home_copy.get("seeCorridor", "see the receipt →")) + "</a></td>"
        "</tr>"
    )


def corridor_table_html(corridors, home_copy):
    cols = home_copy.get("corridorTableCols", {})
    rows = "".join(corridor_row_html(c, home_copy) for c in corridors)
    return (
        '<div class="waterfall-title">' + esc(home_copy.get("corridorTableTitle", "Every transfer we check, priced the same way")) + "</div>"
        '<table class="corridor-table"><thead><tr>'
        "<th>" + esc(cols.get("corridor", "SENDING")) + "</th>"
        "<th>" + esc(cols.get("stablecoin", "STABLECOIN COST")) + "</th>"
        "<th>" + esc(cols.get("fiat", "BEST APP")) + "</th>"
        "<th>" + esc(cols.get("winRate", "STABLECOIN CHEAPER")) + "</th>"
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
        "headline", "Stablecoins rarely beat the cheapest transfer app. Except where money itself is broken.")))
    changed = changed or ok1

    n_routes = len(doc.get("corridors") or [])
    n_countries = count_countries()
    html, ok2 = replace_by_marker(html, "heroSub", sub_html(home_copy, n_routes, n_countries))
    changed = changed or ok2

    table = corridor_table_html(doc["corridors"], home_copy)
    html, ok3 = replace_by_marker(html, "corridorTableSection", table)
    changed = changed or ok3

    idx_doc = load_index_latest()
    strip = build_premium_strip(idx_doc, home_copy)
    if strip is not None:
        html, ok4 = replace_by_marker(html, "premiumStrip", strip)
        changed = changed or ok4
    else:
        print("  no data/index_latest.json countries yet -- leaving premium strip's prior bake in place")

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
