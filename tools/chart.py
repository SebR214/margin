#!/usr/bin/env python3
"""The one chart component (SEB-61 / U6), server-rendered.

Implements the anatomy specified on SEB-61: a headline value, the change over
the window shown, a single indigo line over a fading area, a right-hand gutter
of up to three value labels, a dotted current-value line with a badge, up to
four date labels along the bottom, and range pills offered only where the
data can fill them.

Rendered once here, at generation time in Python, from the same `history`
list that produces the number printed above it -- so the chart can never show
a different "now" than the headline stat on the page (SEB-60/D1). Nothing
here is fabricated: every path, label and pill is a function of the points it
is given.

A companion, `chart.js`, re-runs this same geometry in the browser only to
redraw the plot when a reader picks a different range pill, and to answer
hover with a point's value and date. Nothing it does can appear before this
module's static markup has already painted the chart -- the chart is fully
present with JavaScript off, or `prefers-reduced-motion` on.

Stdlib only.
"""

import datetime as dt

INDIGO = "#5A55E0"
DOWN = "#D0453B"
BACKFILL = "#b9b6b4"
AREA_TOP = "#DCDFFA"

WIDTH = 1000
HEIGHT = 200

# key, label, window in days. 1h/6h/1d need intraday points a one-a-day
# history structurally cannot hold, so they are never offered here -- but the
# check is generic, not hard-coded to "this chart is daily", so the same
# table works if a chart is ever built over hourly points instead.
RANGES = [
    ("1h", "1h", 1 / 24),
    ("6h", "6h", 6 / 24),
    ("1d", "1d", 1),
    ("1w", "1w", 7),
    ("1m", "1m", 30),
    ("3m", "3m", 90),
    ("1y", "1y", 365),
    ("all", "All", None),
]

DAY_NAMES = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def fmt_pct(v):
    """Mirrors the page's own `pct()` -- same rounding, same sign glyph."""
    if v is None:
        return "—"
    sign = "+" if v >= 0 else "−"
    mag = abs(v)
    return sign + f"{mag:.{1 if mag >= 10 else 2}f}" + "%"


def long_date(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {DAY_NAMES[m - 1]} {y}"


def _parsed(points):
    out = []
    for p in points:
        try:
            d = dt.date.fromisoformat(p["date"])
        except (KeyError, ValueError):
            continue
        if p.get("index_pct") is None:
            continue
        out.append({"date": d, "iso": p["date"], "value": p["index_pct"],
                     "backfill": p.get("source") == "daily_backfill_mid"})
    out.sort(key=lambda p: p["date"])
    return out


# A range is only worth its own pill if the window holds enough points to
# show movement, not just its two boundary days. A one-point-per-day series
# can never fill "1h", "6h" or even "1d" this way -- a single daily median
# straddling a one-day window is a dot, not a line -- and that falls out of
# this rule on its own, without hard-coding "this chart is daily".
MIN_POINTS_IN_WINDOW = 4


def available_ranges(points):
    """Range keys the given points can actually fill, "all" always last."""
    pts = _parsed(points)
    if len(pts) < 2:
        return []
    span_days = (pts[-1]["date"] - pts[0]["date"]).days
    out = []
    for key, label, window in RANGES:
        if window is None:
            out.append((key, label))
            continue
        if span_days < window:
            continue
        in_window = [p for p in pts if (pts[-1]["date"] - p["date"]).days <= window]
        if len(in_window) >= MIN_POINTS_IN_WINDOW:
            out.append((key, label))
    return out


def slice_range(points, key):
    pts = _parsed(points)
    if key == "all" or not pts:
        return pts
    window = next((w for k, _, w in RANGES if k == key), None)
    if not window:
        return pts
    cutoff = pts[-1]["date"] - dt.timedelta(days=window)
    return [p for p in pts if p["date"] >= cutoff]


def _runs(pts):
    """Split into contiguous runs: a run ends at a day-gap or a source change."""
    runs = []
    cur = []
    for p in pts:
        if cur and (p["date"] - cur[-1]["date"]).days == 1 and p["backfill"] == cur[-1]["backfill"]:
            cur.append(p)
        else:
            if cur:
                runs.append(cur)
            cur = [p]
    if cur:
        runs.append(cur)
    return runs


def _geometry(pts):
    values = [p["value"] for p in pts]
    lo, hi = min(values + [0]), max(values + [0])
    pad = (hi - lo) * 0.12 or 1
    lo -= pad
    hi += pad
    n = len(pts)

    def x(i):
        return (i / (n - 1)) * WIDTH if n > 1 else 0

    def y(v):
        return HEIGHT - ((v - lo) / (hi - lo)) * HEIGHT

    return lo, hi, x, y


def build(points, *, default_range="all"):
    """Everything the template needs to draw one chart, computed once."""
    ranges = available_ranges(points)
    pts = slice_range(points, default_range if any(k == default_range for k, _ in ranges) else "all")
    if len(pts) < 2:
        return {"has_data": False, "ranges": ranges, "range": default_range}

    lo, hi, x, y = _geometry(pts)
    idx_by_id = {id(p): i for i, p in enumerate(pts)}

    svg_parts = []
    for run in _runs(pts):
        colour = BACKFILL if run[0]["backfill"] else INDIGO
        if len(run) == 1:
            i = idx_by_id[id(run[0])]
            svg_parts.append(
                f'<circle cx="{x(i):.1f}" cy="{y(run[0]["value"]):.1f}" r="2.5" '
                f'fill="{colour}"/>')
            continue
        seg = " L ".join(f"{x(idx_by_id[id(p)]):.1f} {y(p['value']):.1f}" for p in run)
        if not run[0]["backfill"]:
            first_i, last_i = idx_by_id[id(run[0])], idx_by_id[id(run[-1])]
            area = (f'M {x(first_i):.1f} {HEIGHT} L {seg} L {x(last_i):.1f} {HEIGHT} Z')
            svg_parts.append(f'<path d="{area}" fill="url(#chartFade)"/>')
        svg_parts.append(
            f'<path d="M {seg}" fill="none" stroke="{colour}" stroke-width="1.6" '
            f'vector-effect="non-scaling-stroke"/>')

    last = pts[-1]
    badge_y = y(last["value"])
    svg_parts.append(
        f'<line x1="0" x2="{WIDTH}" y1="{badge_y:.1f}" y2="{badge_y:.1f}" '
        f'stroke="{INDIGO}" stroke-width="1" stroke-dasharray="1 3" '
        f'vector-effect="non-scaling-stroke"/>')

    badge_pct = badge_y / HEIGHT * 100
    gutter = []
    for frac, val in ((0.0, hi), (0.5, (hi + lo) / 2), (1.0, lo)):
        top_pct = frac * 100
        if abs(top_pct - badge_pct) < 12:
            continue
        gutter.append({"top_pct": round(top_pct, 1), "text": fmt_pct(val)})

    first = pts[0]
    change_pts = last["value"] - first["value"]
    if round(change_pts, 2) == 0:
        change_text, change_colour = "No change over the period", "var(--muted)"
    else:
        sign = "+" if change_pts >= 0 else "−"
        points_txt = f"{sign}{abs(change_pts):.2f} points"
        # A relative percent is only honest when the value didn't cross zero --
        # past that point "up 400%" is a real division, not a real story.
        if first["value"] != 0 and (first["value"] > 0) == (last["value"] > 0):
            rel = change_pts / abs(first["value"]) * 100
            dir_word = "up" if change_pts >= 0 else "down"
            points_txt += f", {dir_word} {abs(rel):.1f}%"
        change_text = points_txt
        change_colour = INDIGO if change_pts >= 0 else DOWN

    date_idxs = sorted(set(round(f * (len(pts) - 1)) for f in (0, 1 / 3, 2 / 3, 1)))
    dates = []
    for j, i in enumerate(date_idxs):
        align = "start" if j == 0 else ("end" if j == len(date_idxs) - 1 else "middle")
        dates.append({"text": long_date(pts[i]["iso"]), "align": align})

    return {
        "has_data": True,
        "ranges": ranges,
        "range": default_range if any(k == default_range for k, _ in ranges) else "all",
        "headline": fmt_pct(last["value"]),
        "change_text": change_text,
        "change_colour": change_colour,
        "svg": "".join(svg_parts),
        "gutter": gutter,
        "badge": {"top_pct": round(badge_pct, 1), "text": fmt_pct(last["value"])},
        "dates": dates,
        "points_json": [{"date": p["iso"], "index_pct": p["value"],
                          "backfill": p["backfill"]} for p in pts],
    }


def render_html(points, *, root_id="chart"):
    """The full static fragment: fully rendered with no JavaScript at all."""
    c = build(points)
    if not c["has_data"]:
        return (f'<div id="{root_id}" class="chart" data-points="[]">'
                '<p class="muted small">Not enough days yet to draw a line. '
                'Every point collected is shown.</p></div>')

    pills = ""
    if len(c["ranges"]) > 1:
        buttons = "".join(
            f'<button type="button" class="chart-pill{" is-on" if k == c["range"] else ""}" '
            f'data-range="{k}">{label}</button>'
            for k, label in c["ranges"])
        pills = f'<div class="chart-pills">{buttons}</div>'

    gutter = "".join(
        f'<span class="chart-gutter-label" style="top:{g["top_pct"]}%">{g["text"]}</span>'
        for g in c["gutter"])

    dates = "".join(
        f'<span class="chart-date" style="text-align:{d["align"]}">{d["text"]}</span>'
        for d in c["dates"])

    import json as _json
    points_json = _json.dumps(c["points_json"])

    return f"""<div id="{root_id}" class="chart" data-points='{points_json}'>
  <div class="chart-head">
    <div class="chart-value">{c["headline"]}</div>
    <div class="chart-change" style="color:{c["change_colour"]}">{c["change_text"]}</div>
  </div>
  <div class="chart-plot-row">
    <div class="chart-plot-wrap">
      <svg class="chart-svg" viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none">
        <defs>
          <linearGradient id="chartFade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="{AREA_TOP}" stop-opacity="0.95"/>
            <stop offset="100%" stop-color="{AREA_TOP}" stop-opacity="0.05"/>
          </linearGradient>
        </defs>
        {c["svg"]}
      </svg>
      <div class="chart-badge" style="top:{c["badge"]["top_pct"]}%">{c["badge"]["text"]}</div>
      <div class="chart-hover" hidden></div>
    </div>
    <div class="chart-gutter">{gutter}</div>
  </div>
  <div class="chart-dates">{dates}</div>
  {pills}
</div>"""
