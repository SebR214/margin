#!/usr/bin/env python3
"""Per-country index files, and the index snapshot. Stdlib only.

Implements METHODOLOGY, "The index, version 1" — read that section before
changing anything here. The rules it fixes, in one place:

  index = (price to BUY one USDT locally / official USD rate - 1) * 100

  Source class, in strict precedence, never blended:
    order_book_median / order_book_single   from order books
    broker_median     / broker_single       from broker quotes
    p2p_buy_median                          from person-to-person ads

  round_trip_pct is published beside the index, never folded into it.
  No market is filtered out. A country with no buy side has no value that
  hour, and the row carries the reason.

Derived, never authoritative. Every value is computed from a row in
data/basis.csv or data/p2p_basis.csv; nothing is interpolated and a missing
input produces an absent key rather than a placeholder.

No wall clock in the output, so an unchanged dataset regenerates byte-identical
files and the collector's "nothing staged" branch stays reachable.

Usage: python3 tools/emit_countries.py
"""

import collections
import csv
import datetime as dt
import json
import os
import statistics
import sys

INDEX_VERSION = "1.1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
BASIS = os.path.join(DATA, "basis.csv")
P2P = os.path.join(DATA, "p2p_basis.csv")
SIDES = os.path.join(DATA, "p2p_sides.csv")
FX = os.path.join(DATA, "fx_rates.csv")
HIST = os.path.join(DATA, "basis_history.csv")
OUT_DIR = os.path.join(DATA, "countries")
OUT_INDEX = os.path.join(DATA, "index_latest.json")
PAGE_DIR = os.path.join(HERE, "c")

# Country names for display. Labels only, never numbers — same rule as the
# site's CITY/META maps.
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

# Denominator class, per METHODOLOGY "The denominator, and where it is a policy
# number". A `managed` reference is a rate an authority sets and defends, so the
# index measures distance from a policy number rather than a market spread; a
# `pegged` one reads near zero by construction and that is the finding. Anything
# not listed is treated as `market`.
MANAGED = {"ARS", "VES", "LBP", "SDG", "DZD", "SYP", "IQD", "AFN", "MZN",
           "ETB", "NGN", "AOA", "UAH", "TND", "MMK", "ZWL"}
PEGGED = {"AED", "SAR", "QAR", "KWD", "JOD", "BND", "XAF", "XOF"}

# v1.1 evidence rule, per METHODOLOGY. A P2P value is published only with at
# least MIN_BUY_ADS ads on the buy side AND a buyer's price at or above the
# seller's. Both are about whether a price is evidence, not about whether it is
# convenient: the first rejects a number resting on two ads, the second rejects
# a crossed board where the two sides are not the same market.
MIN_BUY_ADS = 10

# Sanity bands. A value outside these is not wrong by definition -- Sudan's
# +1200% is arithmetic against a policy rate -- but it does not go into the
# ranked snapshot until a human has checked it against an outside reference and
# recorded the check. See METHODOLOGY, "Checked against".
BAND_HIGH, BAND_LOW = 200.0, -3.0

# Outside-band values that HAVE been checked, with the reference that explains
# them. Anything outside the bands and not listed here is published on its own
# page with an "unverified" label and left out of index_latest.json.
VERIFIED_OUTLIERS = {
    "SDG": ("2026-09-10", "The board is internally coherent -- buy 7,015-7,100 "
                          "against sell 6,901-6,960, a 2.9% round trip, every ad on "
                          "Bank of Khartoum. The figure is the distance from an "
                          "official rate of 544 that no transaction uses."),
}

# The evidence behind a number, in the words a reader uses. "3 order books"
# and "31 people selling" are different kinds of claim and the board has to say
# which without using the word "venue".
# A collector's exception is a fact for the record, not a sentence for a
# reader. The raw string stays in the country file; this is what a page shows.
def reason_words(raw):
    r = (raw or "").strip()
    if r.startswith("not enough evidence this hour: the buy side is below"):
        return "the buying and selling sides are not the same market here"
    if r.startswith("not enough evidence this hour:"):
        return "too few people selling to call it a price"
    if "no ads at" in r:
        return "nobody is offering to sell dollars here right now"
    if "no FX mid" in r:
        return "no official exchange rate published for this currency this hour"
    return "no price collected this hour"


def evidence_words(cls, n):
    n = int(n or 0)
    if cls in ("order_book_median", "order_book_single"):
        return f"{n} order book" + ("" if n == 1 else "s")
    if cls in ("broker_median", "broker_single"):
        return f"{n} broker quote" + ("" if n == 1 else "s")
    if cls == "p2p_buy_median":
        return f"{n} person selling" if n == 1 else f"{n} people selling"
    if cls == "p2p_fallback":
        return "an independent price check"
    return "no evidence this hour"


CLASS_WORDS = {
    "order_book_median": "from order books",
    "order_book_single": "from an order book",
    "broker_median": "from broker quotes",
    "broker_single": "from a broker quote",
    "p2p_buy_median": "from person-to-person ads",
    "p2p_fallback": "from an independent price source",
}


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
    return v if v == v else None          # drop NaN


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


def fx_book():
    """{(ccy, hour): row} from data/fx_rates.csv -- the denominator of record.

    The rate that arrived inside a price row is a fallback, not the source of
    truth. This file is, because it says WHERE the rate came from, which a price
    row cannot. Where a central bank publishes its own reference rate the
    collector already preferred it, so reading from here is how that preference
    reaches the index.
    """
    out = {}
    for r in rows(FX):
        t = parse_ts(r.get("ts_utc"))
        ccy = r.get("ccy")
        if t is None or not ccy or num(r, "fx_mid_per_usd") is None:
            continue
        out.setdefault(ccy, []).append((t.replace(minute=0, second=0, microsecond=0), r))
    for ccy in out:
        out[ccy].sort(key=lambda x: x[0])
    return out


def fx_for(book, ccy, hour, fallback):
    """The rate in force for this currency at this hour, and where it came from.

    An official rate is a step function, not an hourly observation: it holds
    until the next one is published. So this takes the newest row AT OR BEFORE
    the price hour rather than demanding an exact match -- the two collectors
    run minutes apart in the same job, and a missed FX hour must not silently
    drop the whole layer back to the fallback.
    """
    series = book.get(ccy) or []
    r = None
    for h, row in series:
        if h <= hour:
            r = row
        else:
            break
    if r is None:
        # Every source available is a DAILY fix, so a rate stamped later the
        # same day is the same published number, not a peek at the future. This
        # is what makes the file usable on the hour it starts, and it is the one
        # place the daily-ness of the sources leaks into the code -- if an
        # intraday source ever appears, delete this branch.
        same_day = [row for h, row in series if h.date() == hour.date()]
        r = same_day[0] if same_day else None
    if r:
        return (num(r, "fx_mid_per_usd"), r.get("source") or "unknown",
                num(r, "parallel_rate_per_usd"), r.get("parallel_source") or "")
    # Before fx_rates.csv existed the rate lived in the price row itself, from
    # open.er-api. Said plainly rather than left to look like a fresh reading.
    return (fallback, "open.er-api (from the price row)", None, "")


def buy_side_counts():
    """{(ccy, hour): n_buy} from the sidecar, empty before it existed."""
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


def is_broker(venue):
    """CriptoYa reports brokers and fintechs quoting a retail spread, not books."""
    return venue.startswith("CriptoYa:")


def buy_price(row):
    """What it costs to BUY one USDT at this venue, and whether it is a real ask.

    The ask is the price a buyer pays. Upbit and Pintu publish a last price
    only, so the last price stands in and the row records that it did — a trade
    that happened is a weaker claim than one currently offered.
    """
    ask = num(row, "usdt_ask")
    if ask:
        return ask, True
    mid = num(row, "usdt_mid")
    return (mid, False) if mid else (None, False)


# --------------------------------------------------------- computation
def index_pct(price, fx):
    if not price or not fx:
        return None
    return round((price / fx - 1) * 100, 4)


def _venue_entry(r):
    price, real_ask = buy_price(r)
    return {
        "venue": r.get("venue"),
        "buy_price": price,
        "is_ask": real_ask,
        "bid": num(r, "usdt_bid"),
        "kind": "broker" if is_broker(r.get("venue") or "") else "order_book",
    }


def latest_by_ccy():
    """Newest hour per currency across both layers -> the index value for it."""
    book_hours = collections.defaultdict(dict)
    for r in rows(BASIS):
        ccy, venue, t = r.get("ccy"), r.get("venue") or "", parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not flag(r, "source_ok") or is_aggregate(venue):
            continue
        if buy_price(r)[0] is None or not num(r, "fx_mid_per_usd"):
            continue
        book_hours[ccy].setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(r)

    p2p_hours = collections.defaultdict(dict)
    for r in rows(P2P):
        ccy, t = r.get("ccy"), parse_ts(r.get("ts_utc"))
        if not ccy or t is None:
            continue
        p2p_hours[ccy].setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(r)

    sides = buy_side_counts()
    book = fx_book()
    out = {}
    for ccy in set(book_hours) | set(p2p_hours):
        entry = {"ccy": ccy, "country": COUNTRY.get(ccy, ccy),
                 "index_version": INDEX_VERSION}
        bh = book_hours.get(ccy) or {}
        ph = p2p_hours.get(ccy) or {}
        hour = max(list(bh) + list(ph))
        entry["hour_utc"] = hour.isoformat()

        venues = [_venue_entry(r) for r in bh.get(hour, [])]
        books = [v for v in venues if v["kind"] == "order_book"]
        brokers = [v for v in venues if v["kind"] == "broker"]
        row_fx = None
        for r in bh.get(hour, []):
            row_fx = num(r, "fx_mid_per_usd") or row_fx
        fx, fx_source, par_rate, par_source = fx_for(book, ccy, hour, row_fx)

        chosen, cls = None, None
        if books:
            chosen = books
            cls = "order_book_median" if len(books) >= 2 else "order_book_single"
        elif brokers:
            chosen = brokers
            cls = "broker_median" if len(brokers) >= 2 else "broker_single"

        if chosen:
            prices = [v["buy_price"] for v in chosen]
            bids = [v["bid"] for v in chosen if v["bid"]]
            price = statistics.median(prices)
            entry.update(
                source_class=cls, source_words=CLASS_WORDS[cls],
                n_sources=len(chosen), buy_price=round(price, 8),
                fx_mid_per_usd=fx, index_pct=index_pct(price, fx),
                venues=[{"venue": v["venue"], "buy_price": v["buy_price"],
                         "index_pct": index_pct(v["buy_price"], fx),
                         "last_price_used": not v["is_ask"]} for v in chosen],
            )
            if bids:
                sell = statistics.median(bids)
                entry["round_trip_pct"] = round((price / sell - 1) * 100, 4) if sell else None
        else:
            pr = ph.get(hour) or []
            r = pr[0] if pr else None
            if fx is None:
                fx, fx_source, par_rate, par_source = fx_for(
                    book, ccy, hour, num(r, "fx_mid_per_usd") if r is not None else None)
            n_buy = sides.get((ccy, hour))
            if n_buy is None:
                # Rows predating the sidecar carry only the two sides added
                # together. Both sides full is the only combination that
                # guarantees a full buy side, so it is the conservative stand-in
                # and it is recorded as such rather than assumed exact.
                total = num(r, "n_ads") if r is not None else None
                n_buy = MIN_BUY_ADS if (total or 0) >= MIN_BUY_ADS * 2 else 0
                entry["buy_ads_estimated"] = True
            price = num(r, "buy_median") if r is not None else None
            sell = num(r, "sell_median") if r is not None else None
            fails = None
            if r is None or not flag(r, "source_ok") or price is None:
                fails = (r or {}).get("error") or "no buy-side source"
            elif n_buy < MIN_BUY_ADS:
                fails = (f"not enough evidence this hour: {n_buy} buy-side "
                         f"ad{'' if n_buy == 1 else 's'}, {MIN_BUY_ADS} required")
            elif sell is not None and price < sell:
                fails = ("not enough evidence this hour: the buy side is below the "
                         "sell side, so the two are not the same market")
            if fails is None:
                fx = fx if fx else num(r, "fx_mid_per_usd")
                entry.update(
                    source_class="p2p_buy_median",
                    source_words=CLASS_WORDS["p2p_buy_median"],
                    n_sources=n_buy, buy_price=price,
                    fx_mid_per_usd=fx, index_pct=index_pct(price, fx),
                    venues=[{"venue": r.get("source"), "buy_price": price,
                             "index_pct": index_pct(price, fx),
                             "last_price_used": False}],
                )
                if sell:
                    entry["round_trip_pct"] = round((price / sell - 1) * 100, 4)
            else:
                # A second, independent row for this hour (SEB-8: today only
                # NGN's collector ever writes one, on the hours its own board
                # has no ads at all) stands in for the withheld ad-board price.
                fb = next((x for x in pr if x is not r and flag(x, "source_ok")
                           and num(x, "mid") is not None), None)
                if fb is not None:
                    fb_price = num(fb, "mid")
                    fx = fx if fx else num(fb, "fx_mid_per_usd")
                    entry.update(
                        source_class="p2p_fallback",
                        source_words=CLASS_WORDS["p2p_fallback"],
                        n_sources=1, buy_price=fb_price,
                        fx_mid_per_usd=fx, index_pct=index_pct(fb_price, fx),
                        venues=[{"venue": fb.get("source"), "buy_price": fb_price,
                                 "index_pct": index_pct(fb_price, fx),
                                 "last_price_used": False}],
                    )
                else:
                    # Not a filtered market: the hour is recorded, with the
                    # reason, and the country page prints it.
                    entry.update(source_class=None, source_words="no price this hour",
                                 n_sources=0, no_value_reason=fails)
                    if sell is not None and price is not None:
                        entry["round_trip_pct"] = round((price / sell - 1) * 100, 4)
                        entry["withheld_buy_price"] = price

        entry["denominator"] = {
            "source": fx_source,
            "rate_per_usd": fx,
            "class": "managed" if ccy in MANAGED else "pegged" if ccy in PEGGED else "market",
        }
        if par_rate:
            entry["denominator"]["parallel_rate_per_usd"] = par_rate
            entry["denominator"]["parallel_source"] = par_source
            if fx:
                entry["denominator"]["parallel_gap_pct"] = round((par_rate / fx - 1) * 100, 4)
        out[ccy] = entry
    return out


def daily_history():
    """{ccy: [{date, index_pct, source, n}]} — one buy-side median per day.

    The 2024-onward backfill is a daily MID, not a buy side, because that is all
    that layer ever recorded. It is included so the long history is not thrown
    away, and every point carries which it is, so nobody has to guess whether a
    2024 figure means the same thing as a 2026 one.

    The P2P leg applies the same v1.1 evidence rule as `latest_by_ccy()` --
    at least MIN_BUY_ADS on the buy side, and the buy side at or above the
    sell side. Without this an hour the "current" view withholds as "not
    enough evidence" still counted toward the daily median, which is how a
    permanently crossed board (METHODOLOGY, "The evidence rule (v1.1)") ended
    up with a published multi-day index history despite never once clearing
    the bar that gates every other hour.
    """
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    kind = {}
    book_days = set()
    for r in rows(BASIS):
        ccy, venue, t = r.get("ccy"), r.get("venue") or "", parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not flag(r, "source_ok") or is_aggregate(venue):
            continue
        price, _ = buy_price(r)
        v = index_pct(price, num(r, "fx_mid_per_usd"))
        if v is not None:
            per[ccy][t.date()].append(v)
            kind[(ccy, t.date())] = "hourly_buy"
            book_days.add((ccy, t.date()))
    sides = buy_side_counts()
    for r in rows(P2P):
        ccy, t = r.get("ccy"), parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not flag(r, "source_ok"):
            continue
        if (ccy, t.date()) in book_days:
            continue                       # an order book outranks the ad board
        price, sell = num(r, "buy_median"), num(r, "sell_median")
        hour = t.replace(minute=0, second=0, microsecond=0)
        n_buy = sides.get((ccy, hour))
        if n_buy is None:
            # Same conservative stand-in as latest_by_ccy(): rows predating the
            # sidecar carry only the two sides summed, and both sides full is
            # the only combination that guarantees a full buy side.
            total = num(r, "n_ads")
            n_buy = MIN_BUY_ADS if (total or 0) >= MIN_BUY_ADS * 2 else 0
        if n_buy < MIN_BUY_ADS:
            continue                       # too few buy-side ads to be evidence
        if sell is not None and price is not None and price < sell:
            continue                       # crossed board: not the same market
        v = index_pct(price, num(r, "fx_mid_per_usd"))
        if v is not None:
            per[ccy][t.date()].append(v)
            kind.setdefault((ccy, t.date()), "hourly_buy_p2p")
    for r in rows(HIST):
        ccy = r.get("ccy")
        b = num(r, "basis_bps")
        try:
            d = dt.date.fromisoformat((r.get("date") or "").strip())
        except ValueError:
            continue
        if not ccy or b is None or per[ccy].get(d):
            continue
        per[ccy][d].append(round(b / 100, 4))
        kind[(ccy, d)] = "daily_backfill_mid"

    out = {}
    for ccy, days in per.items():
        out[ccy] = [{"date": d.isoformat(),
                     "index_pct": round(statistics.median(v), 4),
                     "n": len(v), "source": kind.get((ccy, d), "hourly_buy")}
                    for d, v in sorted(days.items())]
    return out


# ------------------------------------------------------------------ I/O
PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>margin.wiki — what a dollar costs in __COUNTRY__</title>
<meta name="description" content="How much it costs to buy a dollar in __COUNTRY__ compared with the official exchange rate, measured every hour from real exchanges."/>
<link rel="stylesheet" href="../vendor/fonts/fonts.css"/>
<style>
  :root{
    --bg:#f3f2f2; --ink:#201e1d; --muted:#7d7979;
    --line:color-mix(in srgb,#201e1d 18%,transparent);
    --rule:color-mix(in srgb,#201e1d 40%,transparent);
    --fill:#d2d9f7; --deep:#8b9ae8;
    --head:"Archivo",system-ui,sans-serif;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--head);
       font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
  .wrap{max-width:960px;margin:0 auto;padding:0 24px 64px}
  header{display:flex;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid var(--rule);
         font-size:11px;letter-spacing:.1em;text-transform:uppercase}
  header a{color:var(--ink);text-decoration:none}
  header a:hover{text-decoration:underline}
  h1{font-size:40px;line-height:1.08;margin:36px 0 10px;max-width:22ch}
  .lede{font-size:17px;max-width:60ch;margin:0 0 4px}
  .muted{color:var(--muted)}
  .small{font-size:12px}
  .stat{font-family:var(--head);font-weight:800;font-size:34px;line-height:1}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
        gap:2px;background:var(--rule);margin:26px 0 8px}
  .cell{background:var(--bg);padding:13px 15px}
  .k{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  h2{font-size:22px;margin:38px 0 4px;border-bottom:2px solid var(--ink);padding-bottom:8px}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th{text-align:left;font-size:10px;letter-spacing:.1em;text-transform:uppercase;
     color:var(--muted);font-weight:400;padding:10px 0 6px}
  td{padding:9px 0;border-top:1px solid var(--line)}
  td.n{text-align:right;font-family:var(--head);font-weight:800}
  svg{width:100%;height:230px;display:block}
  .empty{padding:22px 0;color:var(--muted)}
  .banner{margin:22px 0 -8px;padding:11px 14px;border:1px solid var(--ink);
          font-size:13px;line-height:1.45}
  .banner b{letter-spacing:.08em;text-transform:uppercase;font-size:11px;
            display:block;margin-bottom:3px}
  @media(max-width:640px){h1{font-size:29px}.stat{font-size:26px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <a href="../index.html"><b>margin.wiki</b></a>
    <a href="../index.html">← all countries</a>
    <a href="../methodology.html">methodology</a>
    <span class="muted" id="stamp"></span>
  </header>
  <div id="banner"></div>
  <h1 id="h1">—</h1>
  <p class="lede" id="lede"></p>
  <p class="muted small" id="caveat"></p>

  <div class="grid" id="stats"></div>

  <h2>How it has moved</h2>
  <p class="muted small" id="histnote"></p>
  <svg id="chart" viewBox="0 0 1000 230" preserveAspectRatio="none"></svg>
  <div class="muted small" id="axis" style="display:flex;justify-content:space-between;padding-top:6px"></div>

  <h2 id="exch-h">Where the price comes from</h2>
  <div id="exch"></div>

  <h2>The small print</h2>
  <p class="small" id="print"></p>
  <p class="small muted">Every figure is read from
     <a href="../data/countries/__CCY__.json">data/countries/__CCY__.json</a>,
     regenerated every hour from
     <a href="../data/basis.csv">basis.csv</a> and
     <a href="../data/p2p_basis.csv">p2p_basis.csv</a>. Nothing is smoothed,
     estimated or filled in.</p>
</div>
<script>
const CCY = "__CCY__";
const pct = v => v == null || !isFinite(v) ? "—"
  : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(Math.abs(v) >= 10 ? 1 : 2) + "%";
const words = v => v == null || !isFinite(v) ? "—"
  : Math.abs(v).toFixed(Math.abs(v) >= 10 ? 1 : 2) + "%" + (v >= 0 ? " more" : " less");
const DAY = ["January","February","March","April","May","June","July",
             "August","September","October","November","December"];
function longDate(iso){
  if(!iso) return "—";
  const [y,m,d] = iso.split("-").map(Number);
  return `${d} ${DAY[m-1]} ${y}`;
}
fetch("../data/countries/" + CCY + ".json", {cache:"no-store"})
  .then(r => { if(!r.ok) throw new Error(r.status); return r.json(); })
  .then(render)
  .catch(e => {
    document.getElementById("h1").textContent = "No data for " + CCY;
    document.getElementById("lede").textContent =
      "data/countries/" + CCY + ".json could not be read (" + e.message + ").";
  });

function render(d){
  const c = d.country;
  const notes = [];
  document.title = "margin.wiki — what a dollar costs in " + c;
  document.getElementById("stamp").textContent =
    "hour " + (d.hour_utc || "").slice(0,13).replace("T"," ") + "Z";

  if(d.index_pct == null){
    const r = d.no_value_reason || "";
    const thin = r.indexOf("not enough evidence") === 0;
    document.getElementById("h1").textContent = thin
      ? "Not enough evidence this hour for " + c
      : "No price for " + c + " this hour";
    document.getElementById("lede").textContent = r
      ? r.replace(/^not enough evidence this hour: /, "The rule was not met: ")
      : "No source reported a price to buy a dollar this hour.";
    notes.push("A number was collected and stored; it is not published because it "
             + "does not meet the evidence rule in the index definition. This is "
             + "recorded every hour, with the reason, and is never a market "
             + "quietly filtered out.");
    if(d.withheld_buy_price != null){
      notes.push("The buy-side price the board showed was "
        + Number(d.withheld_buy_price).toLocaleString("en-US",{maximumFractionDigits:4})
        + ", and the round trip was " + pct(d.round_trip_pct) + ".");
    }
  } else {
    document.getElementById("h1").textContent =
      "A dollar costs " + words(d.index_pct) + " than the official rate in " + c + ".";
    document.getElementById("lede").textContent =
      "That is what it costs to buy one dollar " + d.source_words +
      ", measured against the official exchange rate captured in the same second.";
  }

  if(d.denominator && d.denominator.class === "managed"){
    notes.push("The official rate for " + c + " is a number the authorities set and "
             + "defend, not a market price. Any figure here is the distance from that "
             + "policy rate.");
  } else if(d.denominator && d.denominator.class === "pegged"){
    notes.push(c + "'s currency is pegged, so this figure sits near zero by design. "
             + "That it stays near zero is the finding.");
  }
  document.getElementById("caveat").textContent = notes.join(" ");

  const b = document.getElementById("banner");
  if(d.unverified){
    b.innerHTML = '<div class="banner"><b>Unverified</b>' + d.unverified_reason + "</div>";
  } else if(d.outlier_checked){
    b.innerHTML = '<div class="banner"><b>Checked ' + d.outlier_checked.date + "</b>"
      + "This figure sits outside the normal range and has been checked against an "
      + "outside reference. " + d.outlier_checked.explanation + "</div>";
  } else { b.innerHTML = ""; }

  const cells = [
    ["What a dollar costs", words(d.index_pct),
     "against the official rate"],
    ["Round trip", pct(d.round_trip_pct),
     "buying then selling again"],
    ["Where it comes from", (d.source_words || "—").replace(/^from /,""),
     d.n_sources === 1 ? "1 source" : d.n_sources + " sources"],
    ["History since", longDate(d.history_start),
     d.history_days + (d.history_days === 1 ? " day" : " days") + " of readings"],
  ];
  document.getElementById("stats").innerHTML = cells.map(([k,v,s]) =>
    `<div class="cell"><div class="k">${k}</div><div class="stat">${v}</div>
     <div class="muted small" style="margin-top:4px">${s}</div></div>`).join("");

  const h = d.history || [];
  const back = h.filter(p => p.source === "daily_backfill_mid").length;
  document.getElementById("histnote").textContent = h.length < 2
    ? "Not enough days yet to draw a line. Every point collected is shown."
    : "One point per day, the middle reading of that day. Readings start "
      + longDate(d.history_start) + "."
      + (back ? " The first " + back + " days are a daily backfill of the mid-market price, "
              + "which is a slightly different measurement and is drawn in grey." : "");
  drawChart(h);

  const vs = d.venues || [];
  document.getElementById("exch-h").textContent =
    vs.length > 1 ? "The " + vs.length + " sources behind it" : "Where the price comes from";
  document.getElementById("exch").innerHTML = !vs.length
    ? '<div class="empty">No source reported a price this hour.</div>'
    : `<table><tr><th>Source</th><th style="text-align:right">Price of one dollar</th>
       <th style="text-align:right">Against official</th></tr>` +
      vs.map(v => `<tr><td>${v.venue}${v.last_price_used
        ? ' <span class="muted small">— last traded price, no live offer</span>' : ""}</td>
        <td class="n">${v.buy_price === null ? "—" : Number(v.buy_price).toLocaleString("en-US",{maximumFractionDigits:4})}</td>
        <td class="n">${pct(v.index_pct)}</td></tr>`).join("") + "</table>";

  const den = d.denominator || {};
  const parallel = den.parallel_rate_per_usd == null ? "" :
    " A parallel rate is published for " + c + " as well: "
    + Number(den.parallel_rate_per_usd).toLocaleString("en-US",{maximumFractionDigits:4})
    + " " + d.ccy + " to the dollar from " + (den.parallel_source || "a public feed")
    + ", which is " + pct(den.parallel_gap_pct) + " from the official rate. "
    + "It is recorded beside the official rate and never used in its place.";
  document.getElementById("print").textContent =
    "The official rate used is " + (den.rate_per_usd === null || den.rate_per_usd === undefined
      ? "not available this hour" : Number(den.rate_per_usd).toLocaleString("en-US",{maximumFractionDigits:4})
        + " " + d.ccy + " to the dollar")
    + ", from " + (den.source || "—") + ", classed as a " + (den.class || "—") + " rate."
    + parallel + " "
    + "Index definition version " + d.index_version + ". "
    + "This page shows the price to buy a dollar, never a midpoint — "
    + "buying and selling can be different markets.";
}

function drawChart(h){
  const svg = document.getElementById("chart"), ax = document.getElementById("axis");
  if(h.length < 2){ svg.innerHTML = ""; ax.textContent = ""; return; }
  const vs = h.map(p => p.index_pct);
  let lo = Math.min(0, ...vs), hi = Math.max(0, ...vs);
  const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
  const X = i => (i / (h.length - 1)) * 1000;
  const Y = v => 222 - ((v - lo) / (hi - lo)) * 214;
  const seg = (from, to, colour) => {
    const pts = [];
    for(let i = from; i <= to; i++) pts.push(X(i).toFixed(1) + " " + Y(vs[i]).toFixed(1));
    return pts.length < 2 ? "" :
      `<path d="M ${pts.join(" L ")}" fill="none" stroke="${colour}" stroke-width="1.6"
       vector-effect="non-scaling-stroke"/>`;
  };
  let split = h.findIndex(p => p.source !== "daily_backfill_mid");
  if(split < 0) split = h.length - 1;
  let s = `<line x1="0" x2="1000" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"
            stroke="#7d7979" stroke-dasharray="4 4" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
  if(split > 0) s += seg(0, split, "#b9b6b4");
  s += seg(Math.max(split - 1, 0), h.length - 1, "#8b9ae8");
  svg.innerHTML = s;
  ax.innerHTML = `<span>${longDate(h[0].date)}</span>
                  <span>${pct(lo)} to ${pct(hi)}</span>
                  <span>${longDate(h[h.length-1].date)}</span>`;
}
</script>
</body>
</html>
"""


def build():
    latest = latest_by_ccy()
    hist = daily_history()
    files = {}
    for ccy, entry in latest.items():
        h = hist.get(ccy, [])
        doc = dict(entry)
        doc["history"] = h
        doc["history_start"] = h[0]["date"] if h else None
        doc["history_days"] = len(h)
        files[ccy] = doc

    # A value outside the bands stays on its own page and keeps its number.
    # What it loses is its place in the ranked snapshot, until a check against
    # an outside reference is recorded in VERIFIED_OUTLIERS.
    for f in files.values():
        v = f.get("index_pct")
        if v is None or BAND_LOW <= v <= BAND_HIGH:
            continue
        chk = VERIFIED_OUTLIERS.get(f["ccy"])
        if chk:
            f["outlier_checked"] = {"date": chk[0], "explanation": chk[1]}
        else:
            f["unverified"] = True
            f["unverified_reason"] = (
                f"{v:+.2f}% is outside the sanity band of {BAND_LOW:+g}% to "
                f"{BAND_HIGH:+g}% and has not yet been checked against an outside "
                f"reference. The number is published here and left out of the "
                f"ranked index until it has been.")

    listed = [f for f in files.values()
              if f.get("index_pct") is not None and not f.get("unverified")]
    listed.sort(key=lambda f: f["index_pct"], reverse=True)
    snapshot = {
        "index_version": INDEX_VERSION,
        # Rows carry everything the board needs, so the page makes one request
        # rather than 42. `spark` is the last 30 daily points, which is what a
        # sparkline needs and nothing more.
        "countries": [dict(
            {k: f.get(k) for k in
             ("ccy", "country", "index_pct", "round_trip_pct", "source_class",
              "source_words", "n_sources", "hour_utc", "history_start")},
            denominator_class=(f.get("denominator") or {}).get("class"),
            evidence_words=evidence_words(f.get("source_class"), f.get("n_sources")),
            spark=[p["index_pct"] for p in (f.get("history") or [])[-30:]],
        ) for f in listed],
        # Withheld countries are named, with the reason, so the board can show
        # them rather than let them vanish.
        "withheld": [{"ccy": f["ccy"], "country": f.get("country"),
                      "reason": reason_words(f.get("no_value_reason")),
                      "reason_raw": f.get("no_value_reason") or "",
                      "denominator_class": (f.get("denominator") or {}).get("class")}
                     for f in sorted(files.values(), key=lambda x: x["ccy"])
                     if f.get("index_pct") is None],
        "without_value": sorted(f["ccy"] for f in files.values()
                                if f.get("index_pct") is None),
        "unverified": sorted(f["ccy"] for f in files.values() if f.get("unverified")),
        "sanity_band": {"low_pct": BAND_LOW, "high_pct": BAND_HIGH},
        "min_buy_ads": MIN_BUY_ADS,
        "sources": ["data/basis.csv", "data/p2p_basis.csv", "data/basis_history.csv"],
    }
    stamps = [f.get("hour_utc") for f in files.values() if f.get("hour_utc")]
    if stamps:
        snapshot["as_of_utc"] = max(stamps)
    return files, snapshot


def main():
    files, snapshot = build()
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        for ccy, doc in files.items():
            with open(os.path.join(OUT_DIR, f"{ccy}.json"), "w") as f:
                json.dump(doc, f, indent=2, sort_keys=True)
                f.write("\n")
        with open(OUT_INDEX, "w") as f:
            json.dump(snapshot, f, indent=2, sort_keys=True)
            f.write("\n")
        # One page per country, so every country has a stable URL that exists as
        # a file rather than a query string. Generated here so a country added
        # to the collector gets a page on its first run with no edit.
        os.makedirs(PAGE_DIR, exist_ok=True)
        for ccy, doc in files.items():
            html = (PAGE_TEMPLATE
                    .replace("__CCY__", ccy)
                    .replace("__COUNTRY__", doc.get("country") or ccy))
            with open(os.path.join(PAGE_DIR, f"{ccy.lower()}.html"), "w") as f:
                f.write(html)
    except OSError as e:
        print(f"  [error] cannot write country files: {e}", file=sys.stderr)
        sys.exit(1)

    n = len(snapshot["countries"])
    print(f"  wrote {len(files)} country files -> data/countries/")
    print(f"  wrote {len(files)} country pages -> c/<ccy>.html")
    print(f"  wrote data/index_latest.json  (index v{INDEX_VERSION}, {n} with a value, "
          f"{len(snapshot['without_value'])} without)")
    if n:
        top, bot = snapshot["countries"][0], snapshot["countries"][-1]
        print(f"    dearest : {top['country']} {top['index_pct']:+.2f}%  ({top['source_words']})")
        print(f"    cheapest: {bot['country']} {bot['index_pct']:+.2f}%  ({bot['source_words']})")
    if snapshot["without_value"]:
        print(f"    no price this hour ({len(snapshot['without_value'])}): "
              f"{', '.join(snapshot['without_value'])}")
    if snapshot["unverified"]:
        print(f"    unverified, excluded from the ranking: "
              f"{', '.join(snapshot['unverified'])}")


if __name__ == "__main__":
    main()
