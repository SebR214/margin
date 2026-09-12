#!/usr/bin/env python3
"""The weekly snapshot: one frozen file and one frozen page per ISO week.

Every other number on this site is live -- it moves as new hours land. This is
the one deliberate exception. METHODOLOGY, "The index, version 1" already
defines a second figure beside the hourly one: "one published weekly: how much
more, or less it costs to buy a dollar in that country than its official
exchange rate... the median of that country's hourly figures across the
published week, so one dislocated hour cannot carry a week." This builds that
figure, once, and never touches it again.

A week is the ISO week (Monday to Sunday, UTC) -- an unambiguous convention
the brief does not pin down itself. A week is eligible once it has fully
elapsed; the week in progress is never shown, because it has not happened yet
to freeze. Once `data/weekly/<week>.json` exists, this script will not
overwrite it even if the source CSVs later change (a late-arriving backfill
row, say) -- that is what "frozen" means. Gaps stay gaps here too: a country
with no hourly reading that week is simply absent from that week's file, not
filled in.

Reuses the exact per-hour composition rules `tools/emit_countries.py` uses for
the daily history (order book > broker > P2P, same evidence and sanity-band
checks), just grouped by week instead of by day, so a weekly figure means the
same thing the daily one already published means. Unlike the daily history,
this does NOT fall back to `basis_history.csv` -- that backfill is a daily
MID, not an hourly buy-side reading, and METHODOLOGY defines the weekly figure
as "the median of that country's HOURLY figures". Mixing it in would also
flood the showcase with ~130 weeks of five-country history predating this
site's live collection, which is not what a week of the live engine looks
like. Stdlib only.

Usage: python3 tools/emit_weekly.py
"""

import collections
import csv
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
BASIS = os.path.join(DATA, "basis.csv")
P2P = os.path.join(DATA, "p2p_basis.csv")
SIDES = os.path.join(DATA, "p2p_sides.csv")
OUT_DIR = os.path.join(DATA, "weekly")
OUT_MANIFEST = os.path.join(DATA, "weekly_latest.json")
OUT_RSS = os.path.join(HERE, "weekly.xml")
PAGE_DIR = os.path.join(HERE, "w")

INDEX_VERSION = "1.1"
MIN_BUY_ADS = 10
# Same bands as emit_countries.py, "The index, version 1". A value outside them
# is not wrong by definition, but it does not go in a ranked snapshot until a
# human has checked it against an outside reference -- see METHODOLOGY,
# "Checked against". Kept in sync by hand; both files say so.
BAND_HIGH, BAND_LOW = 200.0, -3.0
VERIFIED_OUTLIERS = {
    "SDG": ("2026-09-10", "The board is internally coherent -- buy 7,015-7,100 "
                          "against sell 6,901-6,960, a 2.9% round trip, every ad on "
                          "Bank of Khartoum. The figure is the distance from an "
                          "official rate of 544 that no transaction uses."),
}

COUNTRY = {
    "AED": "the United Arab Emirates", "AFN": "Afghanistan", "AMD": "Armenia",
    "AUD": "Australia", "NZD": "New Zealand", "TWD": "Taiwan",
    "AOA": "Angola", "ARS": "Argentina", "AZN": "Azerbaijan", "BDT": "Bangladesh",
    "BND": "Brunei", "BOB": "Bolivia", "BRL": "Brazil", "BWP": "Botswana",
    "CLP": "Chile", "COP": "Colombia", "DZD": "Algeria", "EGP": "Egypt",
    "ETB": "Ethiopia", "GEL": "Georgia", "GHS": "Ghana", "IDR": "Indonesia",
    "INR": "India", "IQD": "Iraq", "JOD": "Jordan", "KES": "Kenya",
    "KHR": "Cambodia", "KRW": "South Korea", "KWD": "Kuwait", "KZT": "Kazakhstan",
    "LAK": "Laos", "LBP": "Lebanon", "LKR": "Sri Lanka", "MAD": "Morocco",
    "MNT": "Mongolia", "MXN": "Mexico", "MZN": "Mozambique", "NGN": "Nigeria",
    "NPR": "Nepal", "PEN": "Peru", "PHP": "the Philippines", "PKR": "Pakistan",
    "QAR": "Qatar", "RWF": "Rwanda", "SAR": "Saudi Arabia", "SDG": "Sudan",
    "SGD": "Singapore", "SYP": "Syria", "THB": "Thailand", "TND": "Tunisia",
    "TRY": "Turkey", "TZS": "Tanzania", "UAH": "Ukraine", "UGX": "Uganda",
    "VES": "Venezuela", "VND": "Vietnam", "XAF": "Central African CFA",
    "XOF": "West African CFA", "ZAR": "South Africa", "ZMW": "Zambia",
}
MANAGED = {"ARS", "VES", "LBP", "SDG", "DZD", "SYP", "IQD", "AFN", "MZN",
           "ETB", "NGN", "AOA", "UAH", "TND", "MMK", "ZWL"}
PEGGED = {"AED", "SAR", "QAR", "KWD", "JOD", "BND", "XAF", "XOF"}


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


def is_aggregate(venue):
    return venue.startswith("CriptoYa (") and venue.endswith(")")


def buy_price(row):
    ask = num(row, "usdt_ask")
    if ask:
        return ask, True
    mid = num(row, "usdt_mid")
    return (mid, False) if mid else (None, False)


def index_pct(price, fx):
    if not price or not fx:
        return None
    return round((price / fx - 1) * 100, 4)


def week_id(date_obj):
    y, w, _ = date_obj.isocalendar()
    return "%d-W%02d" % (y, w)


def week_bounds(wk):
    y, w = wk.split("-W")
    start = dt.date.fromisocalendar(int(y), int(w), 1)
    return start, start + dt.timedelta(days=6)


def buy_side_counts():
    out = {}
    for r in rows(SIDES):
        t = parse_ts(r.get("ts_utc"))
        ccy = r.get("ccy")
        if t is None or not ccy:
            continue
        try:
            out[(ccy, t.replace(minute=0, second=0, microsecond=0))] = int(r.get("n_buy") or 0)
        except ValueError:
            continue
    return out


def weekly_values():
    """{ccy: {week: [index_pct, ...]}} -- every hourly figure, grouped by week.

    Same precedence as emit_countries.py's daily_history(): an order book
    outranks the ad board on a day it has one. Grouping happens at the day
    level first so that precedence rule stays exactly what it already is; a
    week is just the set of days that fall inside it.
    """
    per_day = collections.defaultdict(lambda: collections.defaultdict(list))
    book_days = set()
    for r in rows(BASIS):
        ccy, venue, t = r.get("ccy"), r.get("venue") or "", parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not flag(r, "source_ok") or is_aggregate(venue):
            continue
        price, _ = buy_price(r)
        v = index_pct(price, num(r, "fx_mid_per_usd"))
        if v is not None:
            per_day[ccy][t.date()].append(v)
            book_days.add((ccy, t.date()))
    sides = buy_side_counts()
    for r in rows(P2P):
        ccy, t = r.get("ccy"), parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not flag(r, "source_ok"):
            continue
        if (ccy, t.date()) in book_days:
            continue
        price, sell = num(r, "buy_median"), num(r, "sell_median")
        hour = t.replace(minute=0, second=0, microsecond=0)
        n_buy = sides.get((ccy, hour))
        if n_buy is None:
            total = num(r, "n_ads")
            n_buy = MIN_BUY_ADS if (total or 0) >= MIN_BUY_ADS * 2 else 0
        if n_buy < MIN_BUY_ADS:
            continue
        if sell is not None and price is not None and price < sell:
            continue
        v = index_pct(price, num(r, "fx_mid_per_usd"))
        if v is not None:
            per_day[ccy][t.date()].append(v)

    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for ccy, days in per_day.items():
        for d, values in days.items():
            out[ccy][week_id(d)].extend(values)
    return out


def build_week(wk, values_by_ccy):
    """One frozen week's payload, or None if nothing cleared the bar that week."""
    countries, unverified = [], []
    for ccy, by_week in values_by_ccy.items():
        vs = by_week.get(wk)
        if not vs:
            continue
        v = round(statistics.median(vs), 4)
        cls = "managed" if ccy in MANAGED else "pegged" if ccy in PEGGED else "market"
        entry = {"ccy": ccy, "country": COUNTRY.get(ccy, ccy), "index_pct": v,
                 "n": len(vs), "denominator_class": cls}
        if not (BAND_LOW <= v <= BAND_HIGH):
            chk = VERIFIED_OUTLIERS.get(ccy)
            if chk:
                entry["outlier_checked"] = {"date": chk[0], "explanation": chk[1]}
            else:
                unverified.append(ccy)
                continue
        countries.append(entry)
    if not countries:
        return None
    countries.sort(key=lambda c: c["index_pct"], reverse=True)
    start, end = week_bounds(wk)
    return {
        "week": wk, "start": start.isoformat(), "end": end.isoformat(),
        "index_version": INDEX_VERSION, "min_buy_ads": MIN_BUY_ADS,
        "sanity_band": {"low_pct": BAND_LOW, "high_pct": BAND_HIGH},
        "countries": countries, "unverified": sorted(unverified),
        "sources": ["data/basis.csv", "data/p2p_basis.csv"],
    }


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>margin.wiki — the week of {start_words} to {end_words}</title>
<meta name="description" content="What it cost to buy a dollar, by country, median across every hour of this week. Frozen once the week ended -- these numbers do not move."/>
<link rel="stylesheet" href="../vendor/fonts/fonts.css"/>
<style>
  :root{{
    --bg:#f3f2f2; --ink:#201e1d; --muted:#7d7979;
    --line:color-mix(in srgb,#201e1d 18%,transparent);
    --rule:color-mix(in srgb,#201e1d 40%,transparent);
    --fill:#d2d9f7; --deep:#8b9ae8;
    --head:"Archivo",system-ui,sans-serif;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--head);
       font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}}
  .wrap{{max-width:900px;margin:0 auto;padding:0 24px 64px}}
  header{{display:flex;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid var(--rule);
         font-size:11px;letter-spacing:.1em;text-transform:uppercase;flex-wrap:wrap}}
  header a{{color:var(--ink);text-decoration:none}}
  header a:hover{{text-decoration:underline}}
  h1{{font-size:34px;line-height:1.1;margin:34px 0 8px;max-width:26ch}}
  .lede{{font-size:16px;max-width:64ch;margin:0 0 22px;color:var(--muted)}}
  .muted{{color:var(--muted)}} .small{{font-size:12px}}
  table{{width:100%;border-collapse:collapse;font-size:14px;margin:18px 0}}
  th{{text-align:left;font-size:10px;letter-spacing:.1em;text-transform:uppercase;
     color:var(--muted);font-weight:400;padding:10px 0 6px}}
  td{{padding:8px 0;border-top:1px solid var(--line)}}
  td.n{{text-align:right;font-family:var(--head);font-weight:800}}
  .empty{{padding:26px 0;color:var(--muted)}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <a href="../index.html"><b>margin.wiki</b></a>
    <a href="../index.html">the board</a>
    <a href="../weekly.html">← every week</a>
    <a href="../methodology.html">methodology</a>
    <span class="muted" id="stamp"></span>
  </header>
  <h1>The week of {start_words} to {end_words}.</h1>
  <p class="lede">One figure per country: the median of every hour that country
     cleared this week, so a single dislocated hour cannot carry the week. This
     page is frozen -- once written it is never recomputed, even if the source
     files change later.</p>
  <div id="list"></div>
  <p class="small muted">Every figure is read from
     <a href="../data/weekly/{week}.json">data/weekly/{week}.json</a>, written
     once when the week ended and never rewritten.</p>
</div>
<script>
const WEEK = "{week}";
const words = v => v == null || !isFinite(v) ? "—"
  : Math.abs(v).toFixed(Math.abs(v) >= 10 ? 1 : 2) + "%" + (v >= 0 ? " more" : " less");
fetch("../data/weekly/" + WEEK + ".json", {{cache:"no-store"}})
  .then(r => {{ if(!r.ok) throw new Error(r.status); return r.json(); }})
  .then(render)
  .catch(e => {{
    document.getElementById("list").innerHTML =
      '<div class="empty">No data available for this week ('
      + e.message + ').</div>';
  }});
function render(d){{
  document.getElementById("stamp").textContent =
    d.countries.length + " countries · frozen";
  if(!d.countries.length){{
    document.getElementById("list").innerHTML =
      '<div class="empty">No country cleared the evidence rule this week.</div>';
    return;
  }}
  document.getElementById("list").innerHTML = `
    <table>
      <tr><th>Country</th><th>Dollar cost this week</th><th>Hours counted</th></tr>
      ${{d.countries.map(c => `
        <tr>
          <td>${{c.country}}</td>
          <td class="n">${{words(c.index_pct)}} than the official rate</td>
          <td class="n">${{c.n}}</td>
        </tr>`).join("")}}
    </table>`;
}}
</script>
</body>
</html>
"""

DAY = ["January", "February", "March", "April", "May", "June", "July",
       "August", "September", "October", "November", "December"]


def long_date(d):
    return "%d %s %d" % (d.day, DAY[d.month - 1], d.year)


def write_page(payload):
    start = dt.date.fromisoformat(payload["start"])
    end = dt.date.fromisoformat(payload["end"])
    os.makedirs(PAGE_DIR, exist_ok=True)
    path = os.path.join(PAGE_DIR, payload["week"].lower() + ".html")
    with open(path, "w") as f:
        f.write(PAGE_TEMPLATE.format(
            week=payload["week"], start_words=long_date(start),
            end_words=long_date(end)))


def rfc822(d):
    return d.strftime("%a, %d %b %Y 00:00:00 +0000")


def escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def write_rss(weeks):
    items = []
    for w in weeks:
        start, end = dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"])
        top = w["countries"][0] if w["countries"] else None
        summary = ("%d countries measured. Highest this week: %s, a dollar cost "
                   "%+.2f%% against the official rate, median of %d hours." %
                   (len(w["countries"]), top["country"], top["index_pct"], top["n"])
                   if top else "No country cleared the evidence rule this week.")
        link = "https://margin.wiki/w/%s.html" % w["week"].lower()
        items.append(
            "  <item>\n"
            "    <title>%s</title>\n"
            "    <link>%s</link>\n"
            "    <guid isPermaLink=\"true\">%s</guid>\n"
            "    <pubDate>%s</pubDate>\n"
            "    <description>%s</description>\n"
            "  </item>" % (
                escape("Week of %s to %s" % (long_date(start), long_date(end))),
                link, link, rfc822(end + dt.timedelta(days=1)), escape(summary)))
    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>\n'
        "  <title>margin.wiki — the weekly snapshot</title>\n"
        "  <link>https://margin.wiki/weekly.html</link>\n"
        "  <description>What a dollar cost, by country, one frozen figure per "
        "week.</description>\n"
        + "\n".join(items) + "\n"
        "</channel></rss>\n")
    with open(OUT_RSS, "w") as f:
        f.write(doc)


def main():
    values_by_ccy = weekly_values()
    today = dt.datetime.now(dt.timezone.utc).date()
    all_weeks = sorted({wk for by_week in values_by_ccy.values() for wk in by_week})
    complete = [wk for wk in all_weeks if week_bounds(wk)[1] < today]

    frozen, new = 0, 0
    for wk in complete:
        out_path = os.path.join(OUT_DIR, wk + ".json")
        if os.path.exists(out_path):
            continue
        payload = build_week(wk, values_by_ccy)
        if payload is None:
            continue
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=1, sort_keys=False)
            f.write("\n")
        new += 1

    weeks = []
    if os.path.isdir(OUT_DIR):
        for fname in sorted(os.listdir(OUT_DIR), reverse=True):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(OUT_DIR, fname)) as f:
                weeks.append(json.load(f))
            frozen += 1

    for payload in weeks:
        write_page(payload)
    write_rss(weeks)

    manifest = {
        "as_of_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "weeks": [dict(w, href="w/%s.html" % w["week"].lower()) for w in weeks],
    }
    with open(OUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=False)
        f.write("\n")

    print(f"  weekly: {frozen} weeks on record, {new} newly frozen this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
