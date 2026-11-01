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
data/basis.csv, data/p2p_basis.csv or data/p2p_okx.csv; nothing is interpolated
and a missing input produces an absent key rather than a placeholder.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import source_gate  # SEB-302: only an approved source can feed a number

INDEX_VERSION = "1.9.1"

# v1.5: crossed boards. A board whose buy median is below its sell median is crossed. Two cases are no longer withheld:
#   1. a near tie: crossed by less than NEAR_TIE of the mid counts as not crossed;
#   2. both boards have the evidence and their buy medians are within SECOND_BOARD_MAX_GAP: the price is the median of the two
#      buy medians even if one or both boards are crossed (the published price already comes from the buy side).
# V15 can be turned off by tools/v15_before_after.py to run the v1.4 rule over the same rows.
NEAR_TIE = 0.001
V15 = True
CROSSED_TEXT = "not enough evidence this hour: the buy side is below the sell side"

# v1.2: a second source is used only when it looks alive and agrees with the first.
SECOND_BOARD_MAX_GAP = 0.03     # OKX's buy median must be within 3% of Binance's to be combined with it
STALE_HOURS = 24                # a second source whose price has not changed for this many hours is ignored
STALE_MIN_ROWS = 20             # ...judged only when it has at least this many hourly readings in the window

# v1.4: a sudden flip is held back (SEB-302). A country is compared with its own last 7 days of PUBLISHED numbers
# (data/index_hourly.csv). A number that lands more than HOLD_MIN_POINTS points, or HOLD_RELATIVE of the usual level,
# away from the 7-day median is not published until a second source agrees or HOLD_CONFIRM_HOURS earlier hours
# in a row were already that far away in the same direction (held hours are kept in data/index_held.csv).
HOLD_WINDOW_DAYS = 7
HOLD_MIN_ROWS = 48              # fewer published hours than this in the window and there is nothing to compare with
HOLD_MIN_POINTS = 3.0
HOLD_RELATIVE = 0.25
HOLD_CONFIRM_HOURS = 3


def hold_decision(value, hour, published, held, venue_values):
    """Is `value`, this country's number for `hour`, a sudden flip nobody has confirmed?

    published, held: {hour datetime: index_pct} from index_hourly.csv and index_held.csv.
    venue_values: the index_pct of each source behind this hour's number.
    Returns (state, base, threshold) with state one of: no_judgement, ok, confirmed_by_source,
    confirmed_by_time, hold. Pure, so the test can feed it every case."""
    prior = [v for h, v in published.items() if 0 < (hour - h).total_seconds() <= HOLD_WINDOW_DAYS * 86400]
    if len(prior) < HOLD_MIN_ROWS:
        return "no_judgement", None, None
    base = statistics.median(prior)
    thr = max(HOLD_MIN_POINTS, HOLD_RELATIVE * abs(base))
    d = value - base
    if abs(d) <= thr:
        return "ok", base, thr
    sign = 1 if d > 0 else -1
    if len(venue_values) >= 2 and all((x - base) * sign > thr / 2 for x in venue_values):
        return "confirmed_by_source", base, thr
    seen = dict(held)
    seen.update(published)
    earlier = [seen.get(hour - dt.timedelta(hours=k)) for k in range(1, HOLD_CONFIRM_HOURS + 1)]
    if all(v is not None and (v - base) * sign > thr for v in earlier):
        return "confirmed_by_time", base, thr
    return "hold", base, thr


def _hour_series(path, value_col):
    out = collections.defaultdict(dict)
    for r in rows(path):
        t = parse_ts(r.get("hour_utc"))
        v = num(r, value_col)
        if t is not None and v is not None and r.get("ccy"):
            out[r["ccy"]][t.replace(minute=0, second=0, microsecond=0)] = v
    return out


def unchanged_24h(series, hour):
    """True when `series` ({hour: price}) holds at least STALE_MIN_ROWS readings in the STALE_HOURS up to and
    including `hour` and every one of them is the same price: a live book does not stand still for a day."""
    window = [series[h] for h in (hour - dt.timedelta(hours=k) for k in range(STALE_HOURS)) if h in series]
    return len(window) >= STALE_MIN_ROWS and len(set(window)) == 1

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
BASIS = os.path.join(DATA, "basis.csv")
P2P = os.path.join(DATA, "p2p_basis.csv")
P2P_OKX = os.path.join(DATA, "p2p_okx.csv")
SIDES = os.path.join(DATA, "p2p_sides.csv")
FX = os.path.join(DATA, "fx_rates.csv")
HIST = os.path.join(DATA, "basis_history.csv")
INDEX_HOURLY = os.path.join(DATA, "index_hourly.csv")      # v1.4: what each country published, hour by hour
INDEX_HELD = os.path.join(DATA, "index_held.csv")          # v1.4: numbers held back as a sudden flip
STABLE_SPREAD = os.path.join(DATA, "stable_spread.csv")
OUT_DIR = os.path.join(DATA, "countries")
OUT_INDEX = os.path.join(DATA, "index_latest.json")
OUT_STABLE_SPREAD_SUMMARY = os.path.join(DATA, "stable_spread_summary.json")

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
    "VES": "Venezuela", "VND": "Vietnam", "XAF": "Central Africa",
    "XOF": "West Africa", "ZAR": "South Africa", "ZMW": "Zambia",
}

# Denominator class, per METHODOLOGY "The denominator, and where it is a policy
# number". A `managed` reference is a rate an authority sets and defends, so the
# index measures distance from a policy number rather than a market spread; a
# `pegged` one reads near zero by construction and that is the finding. An
# `unmaintained` reference is a government rate that exists on paper but has
# stopped being updated, so what we divide by is whatever aggregate is left --
# SEB-31, evidence gathered in PR #77. Anything not listed is treated as
# `market`.
MANAGED = {"ARS", "VES", "LBP", "DZD", "SYP", "IQD", "AFN", "MZN",
           "ETB", "NGN", "AOA", "UAH", "TND", "MMK", "ZWL"}
PEGGED = {"AED", "SAR", "QAR", "KWD", "JOD", "BND", "XAF", "XOF"}
UNMAINTAINED = {"SDG"}

# Region, for the countries page's region filter (SEB-270). A geographic
# fact about a currency's country, same kind of label as COUNTRY above --
# not a styling choice, so it lives here rather than in copy.json (RULES.md's
# copy lock governs reader-facing WORDING, not a country's place on a map).
# REGION_ORDER is the canonical display order the countries page's region
# buttons follow; the names themselves are the six the issue approved.
REGION_ORDER = (
    "Middle East and North Africa", "Africa south of the Sahara",
    "Latin America", "Asia", "Europe and the Caucasus", "Oceania",
)
REGION = {
    # Middle East and North Africa
    "DZD": "Middle East and North Africa", "IQD": "Middle East and North Africa",
    "SYP": "Middle East and North Africa", "TND": "Middle East and North Africa",
    "QAR": "Middle East and North Africa", "MAD": "Middle East and North Africa",
    "SAR": "Middle East and North Africa", "KWD": "Middle East and North Africa",
    "EGP": "Middle East and North Africa", "AED": "Middle East and North Africa",
    "LBP": "Middle East and North Africa", "JOD": "Middle East and North Africa",
    "SDG": "Middle East and North Africa",
    # Africa south of the Sahara
    "ZAR": "Africa south of the Sahara", "RWF": "Africa south of the Sahara",
    "TZS": "Africa south of the Sahara", "KES": "Africa south of the Sahara",
    "NGN": "Africa south of the Sahara", "MZN": "Africa south of the Sahara",
    "UGX": "Africa south of the Sahara", "AOA": "Africa south of the Sahara",
    "BWP": "Africa south of the Sahara", "ETB": "Africa south of the Sahara",
    "GHS": "Africa south of the Sahara", "XAF": "Africa south of the Sahara",
    "XOF": "Africa south of the Sahara", "ZMW": "Africa south of the Sahara",
    # Latin America
    "VES": "Latin America", "ARS": "Latin America", "BRL": "Latin America",
    "PEN": "Latin America", "BOB": "Latin America", "MXN": "Latin America",
    "CLP": "Latin America", "COP": "Latin America",
    # Asia
    "KZT": "Asia", "BDT": "Asia", "INR": "Asia", "MNT": "Asia", "PKR": "Asia",
    "LKR": "Asia", "LAK": "Asia", "KHR": "Asia", "KRW": "Asia", "VND": "Asia",
    "TWD": "Asia", "PHP": "Asia", "IDR": "Asia", "SGD": "Asia", "THB": "Asia",
    "AFN": "Asia", "BND": "Asia", "NPR": "Asia",
    # Europe and the Caucasus
    "TRY": "Europe and the Caucasus", "GEL": "Europe and the Caucasus",
    "AZN": "Europe and the Caucasus", "AMD": "Europe and the Caucasus",
    "UAH": "Europe and the Caucasus",
    # Oceania
    "AUD": "Oceania", "NZD": "Oceania",
}

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
    "SDG": ("2026-09-12",
            "The street price stands: about 7,059 SDG to the dollar on the "
            "person-to-person board, a 1.5% round trip between buying and "
            "selling, steady for eight days. The denominator underneath it is "
            "the open question. Sudan's central bank still lists an official "
            "rate at cbos.gov.sd, but that page has not moved since 7 March "
            "2022, when it read 445 SDG to the dollar, so there is no current "
            "government rate to divide by. The 511 we use comes from open.er-api "
            "and slid 544 -> 512 -> 511 in two days, which reads as an aggregate "
            "of the rates commercial banks now set for themselves rather than a "
            "rate the state holds in place. The figure is the distance from that "
            "bank-set reference; the denominator is not changed to make the "
            "number smaller."),
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

# SEB-38: the one CSV a country's figure actually came from, repo-relative.
# The order-book/broker layer and the P2P layer are different files, and an
# hour with no value still tried the P2P layer last (see latest_by_ccy), so
# that is the honest attribution for it too.
SOURCE_FILE_BY_CLASS = {
    "order_book_median": "data/basis.csv", "order_book_single": "data/basis.csv",
    "broker_median": "data/basis.csv", "broker_single": "data/basis.csv",
    "p2p_buy_median": "data/p2p_basis.csv", "p2p_fallback": "data/p2p_basis.csv",
    None: "data/p2p_basis.csv",
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


def crossed(buy, sell):
    """The buy median is below the sell median. v1.5: by less than NEAR_TIE of the mid it is a tie, not crossed."""
    if buy is None or sell is None or buy >= sell:
        return False
    return not V15 or (sell - buy) / ((buy + sell) / 2) >= NEAR_TIE


def boards_agree(ccy, hour, binance_buy, okx_hours, okx_series):
    """v1.5 rule 2: OKX has the evidence in this hour (at least MIN_BUY_ADS, already filtered into okx_hours), its price is
    alive, and its buy median is within SECOND_BOARD_MAX_GAP of Binance's. Whether either board is crossed does not matter."""
    okr = (okx_hours.get(ccy, {}).get(hour) or [None])[0]
    return (okr is not None and not unchanged_24h((okx_series or {}).get(ccy, {}), hour)
            and abs(num(okr, "buy_median") / binance_buy - 1) <= SECOND_BOARD_MAX_GAP)


def board_row_usable(r):
    """A person-to-person row we may price from. It passed the collector's guard, or (v1.5) the guard refused it only because
    it is crossed: such a row keeps its medians as evidence, and whether it is a near tie or agrees with the other board
    is decided here, from the medians."""
    if flag(r, "source_ok"):
        return True
    return (V15 and (r.get("error") or "").startswith(CROSSED_TEXT)
            and num(r, "buy_median") is not None and num(r, "sell_median") is not None)


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


# A gap below this is inside the noise of any one hour (METHODOLOGY, "USDT
# versus USDC on the same venue") and would only clutter a country page.
STABLE_SPREAD_NOTE_PCT = 0.5


def stable_spread_latest():
    """Most recent source_ok (ccy, venue) -> (ts, spread_bps) from stable_spread.csv.

    Keyed by the pair, never by venue alone: a venue that prices two
    currencies would otherwise let one currency's reading leak into the
    other's, and the issue this file exists for is precisely that no
    currency may borrow another's instrument check.
    """
    best = {}
    for r in rows(STABLE_SPREAD):
        if not flag(r, "source_ok"):
            continue
        ccy, venue = r.get("ccy"), r.get("venue")
        t = parse_ts(r.get("ts_utc"))
        spread = num(r, "spread_bps")
        if not ccy or not venue or t is None or spread is None:
            continue
        key = (ccy, venue)
        if key not in best or t > best[key][0]:
            best[key] = (t, spread)
    return best


def instrument_check(ccy, venue_names, spread_latest):
    """Is the dollar this currency's price is built on actually worth a dollar.

    Only venues that both (a) fed this currency's own published price and (b)
    have their own source_ok stable_spread.csv row for this same currency
    count -- never another currency's venues, and never a spread inferred
    from a venue that did not price this currency.
    """
    hits = [(venue, ts, spread) for venue in venue_names
            for ts, spread in [spread_latest.get((ccy, venue), (None, None))]
            if ts is not None]
    if not hits:
        return {"checked": False, "reason": "no venue here lists both"}
    spreads = [h[2] for h in hits]
    return {
        "spread_pct": round(statistics.median(spreads) / 100, 4),
        "venues": sorted(h[0] for h in hits),
        "as_of": max(h[1] for h in hits).isoformat(),
    }


def stable_spread_summary(spread_latest):
    """What methodology.html shows: the dataset's own current shape.

    Every figure here is read straight from stable_spread.csv's most recent
    source_ok rows -- nothing here is the per-currency instrument_check, and
    nothing here decides whether a country page shows a note.
    """
    if not spread_latest:
        return None
    widest_key = max(spread_latest, key=lambda k: abs(spread_latest[k][1]))
    widest_ccy, widest_venue = widest_key
    widest_ts, widest_bps = spread_latest[widest_key]
    pcts = [spread / 100 for _, spread in spread_latest.values()]
    return {
        "venues": len({venue for _, venue in spread_latest}),
        "readings": len(spread_latest),
        "rows": len(rows(STABLE_SPREAD)),
        "range_pct": {"low": round(min(pcts), 4), "high": round(max(pcts), 4)},
        "widest_pct": round(widest_bps / 100, 4),
        "widest_venue": widest_venue,
        "widest_ccy": widest_ccy,
        "as_of": max(ts for ts, _ in spread_latest.values()).isoformat(),
    }


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


# SEB, 2026-09-28: the home page's headline numbers, its country chart and
# its "This hour" line switch from the latest single hourly value to the
# median of a country's last MEDIAN_WINDOW_HOURS real hourly values --
# Algeria's P2P buy-side median jumped 256.5 -> 268.6 DZD (sell side flat
# ~250) overnight while the official rate held, a thin-order-book artifact
# a rolling median absorbs. index_pct (the single latest hour) is unchanged
# and keeps feeding every line chart on the site -- only the ranked home
# chart and headline text read median_24h_pct instead.
MEDIAN_WINDOW_HOURS = 24


def _hour_value(ccy, hour, bh, ph, sides, book, okx_hours=None, okx_series=None):
    """One hour's index value, same source precedence and evidence rule as
    latest_by_ccy() below -- order books/brokers first, then a P2P buy-side
    median that clears the v1.1 evidence bar (>= MIN_BUY_ADS, buy >= sell).
    Never p2p_fallback: that stands in for one missing ad-board row, and
    letting it count as a full observation in a 24-value median would let a
    single thin hour's quote outweigh a real 20-ad reading. Returns None for
    an hour with no evidence-passing value, so the caller can walk further
    back rather than let a withheld hour count as a zero.
    """
    venues = [_venue_entry(r) for r in bh.get(hour, [])]
    books = [v for v in venues if v["kind"] == "order_book"]
    brokers = [v for v in venues if v["kind"] == "broker"]
    chosen = books or brokers
    if chosen:
        prices = [v["buy_price"] for v in chosen]
        price = statistics.median(prices)
        row_fx = None
        for r in bh.get(hour, []):
            row_fx = num(r, "fx_mid_per_usd") or row_fx
        fx, _fx_source, _par_rate, _par_source = fx_for(book, ccy, hour, row_fx)
        return index_pct(price, fx)
    pr = ph.get(hour) or []
    r = pr[0] if pr else None
    if r is None or not board_row_usable(r):
        return None
    price, sell = num(r, "buy_median"), num(r, "sell_median")
    if price is None:
        return None
    n_buy = sides.get((ccy, hour))
    if n_buy is None:
        total = num(r, "n_ads")
        n_buy = MIN_BUY_ADS if (total or 0) >= MIN_BUY_ADS * 2 else 0
    if n_buy < MIN_BUY_ADS:
        return None
    if crossed(price, sell):
        # v1.5 rule 2: both boards agree, so the median of the two buy medians stands in for the crossed board
        if not (V15 and okx_hours is not None and boards_agree(ccy, hour, price, okx_hours, okx_series)):
            return None
        price = statistics.median([price, num(okx_hours[ccy][hour][0], "buy_median")])
    fx, _fx_source, _par_rate, _par_source = fx_for(book, ccy, hour, num(r, "fx_mid_per_usd"))
    return index_pct(price, fx)


def median_24h_by_ccy(book_hours, p2p_hours, sides, book, newest_hour_by_ccy, okx_hours=None, okx_series=None):
    """{ccy: (median_pct, n_hours_used)} -- the median of each currency's
    last MEDIAN_WINDOW_HOURS real, evidence-passing hourly values, walking
    back hour by hour from that currency's own newest hour. Computed
    regardless of whether the CURRENT hour itself passed the evidence rule
    (a thin overnight hour can fail evidence and still leave 23 good hours
    behind it), so a country stays represented on the home chart by its
    real trailing day even on an hour its single reading is withheld.
    Stops as soon as MEDIAN_WINDOW_HOURS real values are found; gives up
    after looking back 3x that many hours so a long gap in real history
    doesn't turn into an unbounded loop.
    """
    out = {}
    for ccy, newest in newest_hour_by_ccy.items():
        bh = book_hours.get(ccy) or {}
        ph = p2p_hours.get(ccy) or {}
        vals = []
        h = newest
        for _ in range(MEDIAN_WINDOW_HOURS * 3):
            v = _hour_value(ccy, h, bh, ph, sides, book, okx_hours, okx_series)
            if v is not None:
                vals.append(v)
            h = h - dt.timedelta(hours=1)
            if len(vals) >= MEDIAN_WINDOW_HOURS:
                break
        if vals:
            out[ccy] = (round(statistics.median(vals), 4), len(vals))
    return out


_REGISTRY = []


def usable(source):
    """True when `source` is approved in data/source_registry.json. A missing or empty registry is a loud failure:
    refusing every source quietly would publish nothing and say nothing."""
    if not _REGISTRY:
        _REGISTRY.append(source_gate.load_registry())
        if not _REGISTRY[0].get("sources"):
            raise SystemExit("data/source_registry.json is missing or empty: run tools/source_gate.py --init and review it")
    return source_gate.approved(source, _REGISTRY[0])


def load_hours():
    """Every usable hourly row, by currency and hour: order books and brokers, Binance person-to-person rows, and OKX rows
    (with the evidence bar), plus every OKX reading for the standing-still check."""
    book_hours = collections.defaultdict(dict)
    for r in rows(BASIS):
        ccy, venue, t = r.get("ccy"), r.get("venue") or "", parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not flag(r, "source_ok") or is_aggregate(venue) or not usable(venue):
            continue
        if buy_price(r)[0] is None or not num(r, "fx_mid_per_usd"):
            continue
        book_hours[ccy].setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(r)

    p2p_hours = collections.defaultdict(dict)
    for r in (rows(P2P) if usable("binance_p2p") else []):
        ccy, t = r.get("ccy"), parse_ts(r.get("ts_utc"))
        if not ccy or t is None:
            continue
        p2p_hours[ccy].setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(r)

    # SEB-256: OKX's own person-to-person board, a second independent source for the same ticket (v1.2).
    okx_hours = collections.defaultdict(dict)
    okx_series = collections.defaultdict(dict)       # every reading, for the 24-hour standing-still check
    for r in (rows(P2P_OKX) if usable("okx_p2p") else []):
        ccy, t = r.get("ccy"), parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not board_row_usable(r) or num(r, "buy_median") is None:
            continue
        okx_series[ccy][t.replace(minute=0, second=0, microsecond=0)] = num(r, "buy_median")
        if (num(r, "n_ads") or 0) < MIN_BUY_ADS:
            continue          # the same evidence bar the Binance board has to meet
        okx_hours[ccy].setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(r)

    return book_hours, p2p_hours, okx_hours, okx_series


def latest_by_ccy():
    """Newest hour per currency across both layers -> the index value for it."""
    book_hours, p2p_hours, okx_hours, okx_series = load_hours()

    # SEB-254: Luno's own NGN book gets the same standing-still check.
    luno_series = collections.defaultdict(dict)
    for r in rows(BASIS):
        if (r.get("venue") or "") == "Luno" and usable("Luno") and flag(r, "source_ok") and buy_price(r)[0] is not None:
            t = parse_ts(r.get("ts_utc"))
            if t is not None:
                luno_series[r.get("ccy")][t.replace(minute=0, second=0, microsecond=0)] = buy_price(r)[0]

    sides = buy_side_counts()
    book = fx_book()
    spread_latest = stable_spread_latest()
    out = {}
    for ccy in set(book_hours) | set(p2p_hours):
        entry = {"ccy": ccy, "country": COUNTRY.get(ccy, ccy),
                 "index_version": INDEX_VERSION}
        bh = book_hours.get(ccy) or {}
        ph = p2p_hours.get(ccy) or {}
        hour = max(list(bh) + list(ph))
        entry["hour_utc"] = hour.isoformat()
        # SEB-38: the newest source row behind this country's figure -- not the
        # wall clock. Kept equal to hour_utc so an unchanged dataset still
        # regenerates a byte-identical file (see ROADMAP, "nothing staged").
        entry["computed_at"] = entry["hour_utc"]

        venues = [_venue_entry(r) for r in bh.get(hour, [])
                  if not ((r.get("venue") or "") == "Luno" and unchanged_24h(luno_series.get(ccy, {}), hour))]
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
                n_sources=len(chosen), source_file=SOURCE_FILE_BY_CLASS[cls],
                buy_price=round(price, 8),
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
            if r is None or not board_row_usable(r) or price is None:
                fails = (r or {}).get("error") or "no buy-side source"
            elif crossed(price, sell) and not (V15 and n_buy >= MIN_BUY_ADS and boards_agree(ccy, hour, price, okx_hours, okx_series)):
                # crossed, and v1.5 rule 2 does not apply: stated as v1.4 stated it
                if not flag(r, "source_ok"):
                    fails = r.get("error")
                elif n_buy < MIN_BUY_ADS:
                    fails = (f"not enough evidence this hour: {n_buy} buy-side "
                             f"ad{'' if n_buy == 1 else 's'}, {MIN_BUY_ADS} required")
                else:
                    fails = ("not enough evidence this hour: the buy side is below the "
                             "sell side, so the two are not the same market")
            elif n_buy < MIN_BUY_ADS:
                fails = (f"not enough evidence this hour: {n_buy} buy-side "
                         f"ad{'' if n_buy == 1 else 's'}, {MIN_BUY_ADS} required")
            if fails is None:
                fx = fx if fx else num(r, "fx_mid_per_usd")
                entry.update(
                    source_class="p2p_buy_median",
                    source_words=CLASS_WORDS["p2p_buy_median"],
                    n_sources=n_buy,
                    source_file=SOURCE_FILE_BY_CLASS["p2p_buy_median"],
                    buy_price=price,
                    fx_mid_per_usd=fx, index_pct=index_pct(price, fx),
                    venues=[{"venue": r.get("source"), "buy_price": price,
                             "index_pct": index_pct(price, fx),
                             "last_price_used": False}],
                )
                if sell and not crossed(price, sell):
                    entry["round_trip_pct"] = round((price / sell - 1) * 100, 4)
                # v1.2: where OKX's board also meets the evidence bar in this same hour, the published price is the
                # median of the two boards' medians, and both boards are listed. n_sources keeps meaning the buy-side
                # ads behind the Binance board; n_boards says how many boards stand behind the price.
                okr = (okx_hours.get(ccy, {}).get(hour) or [None])[0]
                entry["n_boards"] = 1
                if okr is not None:
                    okx_price = num(okr, "buy_median")
                    gap = abs(okx_price / price - 1)
                    if unchanged_24h(okx_series.get(ccy, {}), hour):
                        entry["second_board"] = {"venue": okr.get("source"), "buy_price": okx_price, "combined": False,
                                                 "why": "its price has not changed for 24 hours"}
                    elif gap > SECOND_BOARD_MAX_GAP:
                        entry["second_board"] = {"venue": okr.get("source"), "buy_price": okx_price, "combined": False,
                                                 "why": "more than 3% from the first board"}
                        # v1.4.1: say it as a record, not only as a reason string: both boards' buy medians and how far
                        # apart they are, in percent to two decimals. The price and n_sources are not touched.
                        entry["p2p_sources_apart"] = {"binance_median": price, "okx_median": okx_price,
                                                      "gap_pct": round(gap * 100, 2)}
                    else:
                        both = statistics.median([price, okx_price])
                        entry["venues"].append({"venue": okr.get("source"), "buy_price": okx_price,
                                                "index_pct": index_pct(okx_price, fx), "last_price_used": False})
                        entry.update(buy_price=round(both, 8), index_pct=index_pct(both, fx), n_boards=2)
                        # v1.5: priced although a board is crossed: the page says so (the sellers' sides agree)
                        sides_crossed = [name for name, row in (("binance_p2p", r), ("okx_p2p", okr))
                                         if crossed(num(row, "buy_median"), num(row, "sell_median"))]
                        if sides_crossed:
                            entry["crossed_boards_agree"] = {"crossed": sides_crossed}
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
                        n_sources=1,
                        source_file=SOURCE_FILE_BY_CLASS["p2p_fallback"],
                        buy_price=fb_price,
                        fx_mid_per_usd=fx, index_pct=index_pct(fb_price, fx),
                        venues=[{"venue": fb.get("source"), "buy_price": fb_price,
                                 "index_pct": index_pct(fb_price, fx),
                                 "last_price_used": False}],
                    )
                else:
                    # Not a filtered market: the hour is recorded, with the
                    # reason, and the country page prints it. SEB-38: n_sources
                    # is null, not zero -- zero would read as "checked and
                    # found nothing"; null with no_value_reason says "no
                    # measurement stood behind this hour" instead.
                    entry.update(source_class=None, source_words="no price this hour",
                                 n_sources=None,
                                 source_file=SOURCE_FILE_BY_CLASS[None],
                                 no_value_reason=fails)
                    if sell is not None and price is not None:
                        entry["round_trip_pct"] = round((price / sell - 1) * 100, 4)
                        entry["withheld_buy_price"] = price

        # SEB-268 (9 Oct): where the published number comes from exchanges, show what the person-to-person boards say
        # for the same hour beside it. Only a board with at least MIN_BUY_ADS buy ads counts; both boards: the middle.
        # This is shown on the country page and changes no published number.
        if entry.get("source_class") in ("order_book_median", "order_book_single", "broker_median", "broker_single") and fx:
            beside = []
            pr_ = (ph.get(hour) or [None])[0]
            if pr_ is not None and flag(pr_, "source_ok") and num(pr_, "buy_median"):
                nb = sides.get((ccy, hour))
                if nb is None:
                    nb = MIN_BUY_ADS if (num(pr_, "n_ads") or 0) >= MIN_BUY_ADS * 2 else 0
                if nb >= MIN_BUY_ADS:
                    beside.append(("binance_p2p", num(pr_, "buy_median")))
            ox_ = (okx_hours.get(ccy, {}).get(hour) or [None])[0]
            # 1 Nov: n_ads counts both sides, so 11 ads can be one buy ad. India showed 30.8% over the official rate on 11 ads
            # (buy 124.33, sell 98.0) beside a 6.4% gap. Binance needs MIN_BUY_ADS a side; OKX gets the same bar here.
            if ox_ is not None and (num(ox_, "n_ads") or 0) >= MIN_BUY_ADS * 2:
                beside.append(("okx_p2p", num(ox_, "buy_median")))
            if beside:
                mid = statistics.median([p for _, p in beside])
                entry["p2p_beside"] = {"boards": [b for b, _ in beside], "buy_price": round(mid, 8),
                                       "index_pct": index_pct(mid, fx)}

        entry["denominator"] = {
            "source": fx_source,
            "rate_per_usd": fx,
            "class": ("managed" if ccy in MANAGED
                      else "pegged" if ccy in PEGGED
                      else "unmaintained" if ccy in UNMAINTAINED
                      else "market"),
        }
        if par_rate:
            entry["denominator"]["parallel_rate_per_usd"] = par_rate
            entry["denominator"]["parallel_source"] = par_source
            if fx:
                entry["denominator"]["parallel_gap_pct"] = round((par_rate / fx - 1) * 100, 4)

        venue_names = {v.get("venue") for v in entry.get("venues", []) if v.get("venue")}
        entry["instrument_check"] = instrument_check(ccy, venue_names, spread_latest)
        out[ccy] = entry

    medians = median_24h_by_ccy(
        book_hours, p2p_hours, sides, book,
        {e["ccy"]: parse_ts(e["hour_utc"]) for e in out.values()},
        okx_hours, okx_series,
    )
    for ccy, (m, n) in medians.items():
        out[ccy]["median_24h_pct"] = m
        out[ccy]["median_24h_n"] = n
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
        if not ccy or t is None or not flag(r, "source_ok") or is_aggregate(venue) or not usable(venue):
            continue
        price, _ = buy_price(r)
        v = index_pct(price, num(r, "fx_mid_per_usd"))
        if v is not None:
            per[ccy][t.date()].append(v)
            kind[(ccy, t.date())] = "hourly_buy"
            book_days.add((ccy, t.date()))
    sides = buy_side_counts()
    for r in (rows(P2P) if usable("binance_p2p") else []):
        ccy, t = r.get("ccy"), parse_ts(r.get("ts_utc"))
        if not ccy or t is None or not board_row_usable(r):
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
        if price is not None and crossed(price, sell):
            continue                       # crossed board: not the same market (v1.5: a near tie is not crossed)
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

def apply_holds(latest):
    """Hold back any number that is a sudden flip nobody has confirmed (v1.4). Mutates `latest`."""
    published, held = _hour_series(INDEX_HOURLY, "index_pct"), _hour_series(INDEX_HELD, "index_pct")
    for ccy, entry in latest.items():
        v, hour = entry.get("index_pct"), parse_ts(entry.get("hour_utc"))
        if v is None or hour is None or not entry.get("source_class"):
            continue
        venue_values = [x["index_pct"] for x in entry.get("venues") or [] if isinstance(x, dict) and x.get("index_pct") is not None]
        state, base, thr = hold_decision(v, hour, published.get(ccy, {}), held.get(ccy, {}), venue_values)
        if state != "hold":
            continue
        entry.update(
            held_value=v, baseline_pct=round(base, 4), withheld_buy_price=entry.get("buy_price"),
            index_pct=None, source_class=None, source_words="no price this hour", n_sources=None,
            source_file=SOURCE_FILE_BY_CLASS[None],
            no_value_reason=(f"held back: {v:+.1f}% is {abs(v - base):.1f} points from this country's usual {base:+.1f}% "
                             f"over the last 7 days, and no second source or earlier hour confirms it yet"))


def build():
    latest = latest_by_ccy()
    apply_holds(latest)
    hist = daily_history()
    files = {}
    for ccy, entry in latest.items():
        h = list(hist.get(ccy, []))
        # SEB-60: daily_history() medians every hourly reading landed so far
        # for the newest day, which is a different, still-open window from the
        # single latest hour latest_by_ccy() published as index_pct -- the two
        # disagreed on 37 of 48 countries. There is one published figure for
        # "right now": entry["index_pct"]. The newest history point is that
        # same value, not a second figure computed from the same rows again,
        # so the two cannot drift apart by construction.
        today = (entry.get("hour_utc") or "")[:10]
        if entry.get("index_pct") is not None and today:
            point = {"date": today, "index_pct": entry["index_pct"],
                     "n": entry.get("n_sources"), "source": "current_hour"}
            if h and h[-1]["date"] == today:
                h[-1] = point
            else:
                h.append(point)
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
        # SEB-38: computed_at and source_file ride along with n_sources here --
        # a country's figure carries different sources and a different hour
        # than the snapshot as a whole, so each row states its own.
        "countries": [dict(
            {k: f.get(k) for k in
             ("ccy", "country", "index_pct", "round_trip_pct", "source_class",
              "source_words", "n_sources", "hour_utc", "history_start",
              "computed_at", "source_file", "median_24h_pct", "median_24h_n",
              "buy_price")},
            denominator_class=(f.get("denominator") or {}).get("class"),
            fx_mid_per_usd=(f.get("denominator") or {}).get("rate_per_usd"),
            region=REGION.get(f["ccy"]),
            evidence_words=evidence_words(f.get("source_class"), f.get("n_sources")),
            spark=[p["index_pct"] for p in (f.get("history") or [])[-30:]],
        ) for f in listed],
        # Withheld countries are named, with the reason, so the board can show
        # them rather than let them vanish. median_24h_pct/median_24h_n ride
        # along here too -- a country whose SINGLE current hour is withheld
        # (thin evidence right now) can still have a real trailing-24h median
        # behind it, which is exactly the home page's ranked chart wants to
        # show instead of dropping the country for the hour.
        "withheld": [{"ccy": f["ccy"], "country": f.get("country"),
                      "reason": reason_words(f.get("no_value_reason")),
                      "reason_raw": f.get("no_value_reason") or "",
                      "denominator_class": (f.get("denominator") or {}).get("class"),
                      "n_sources": f.get("n_sources"),
                      "computed_at": f.get("computed_at"),
                      "source_file": f.get("source_file"),
                      "median_24h_pct": f.get("median_24h_pct"),
                      "median_24h_n": f.get("median_24h_n"),
                      **({"held_value": f["held_value"], "baseline_pct": f["baseline_pct"]} if "held_value" in f else {})}
                     for f in sorted(files.values(), key=lambda x: x["ccy"])
                     if f.get("index_pct") is None],
        "without_value": sorted(f["ccy"] for f in files.values()
                                if f.get("index_pct") is None),
        "unverified": sorted(f["ccy"] for f in files.values() if f.get("unverified")),
        "sanity_band": {"low_pct": BAND_LOW, "high_pct": BAND_HIGH},
        "min_buy_ads": MIN_BUY_ADS,
        "sources": ["data/basis.csv", "data/p2p_basis.csv", "data/basis_history.csv"],
        # SEB-270: the countries page's region filter buttons, in the order
        # they should appear. The region names are the same kind of real-world
        # label as COUNTRY above, not reader-facing wording, so they live here.
        "region_order": list(REGION_ORDER),
    }
    # SEB-38: the file-as-a-whole's own provenance, distinct from any one
    # country's row above. n_sources/source_file here describe the snapshot
    # (how many CSVs feed it), not any single figure.
    snapshot["n_sources"] = len(snapshot["sources"])
    snapshot["source_file"] = list(snapshot["sources"])
    stamps = [f.get("hour_utc") for f in files.values() if f.get("hour_utc")]
    if stamps:
        snapshot["as_of_utc"] = max(stamps)
        snapshot["computed_at"] = snapshot["as_of_utc"]
    else:
        snapshot["computed_at"] = None
    return files, snapshot


def main():
    files, snapshot = build()
    spread_summary = stable_spread_summary(stable_spread_latest())
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        for ccy, doc in files.items():
            with open(os.path.join(OUT_DIR, f"{ccy}.json"), "w") as f:
                json.dump(doc, f, indent=2, sort_keys=True)
                f.write("\n")
        with open(OUT_INDEX, "w") as f:
            json.dump(snapshot, f, indent=2, sort_keys=True)
            f.write("\n")
        if spread_summary:
            with open(OUT_STABLE_SPREAD_SUMMARY, "w") as f:
                json.dump(spread_summary, f, indent=2, sort_keys=True)
                f.write("\n")
    except OSError as e:
        print(f"  [error] cannot write country files: {e}", file=sys.stderr)
        sys.exit(1)

    n = len(snapshot["countries"])
    print(f"  wrote {len(files)} country files -> data/countries/")
    print(f"  wrote data/index_latest.json  (index v{INDEX_VERSION}, {n} with a value, "
          f"{len(snapshot['without_value'])} without)")
    if spread_summary:
        print(f"  wrote data/stable_spread_summary.json ({spread_summary['venues']} venues, "
              f"widest {spread_summary['widest_pct']:+.2f}% on "
              f"{spread_summary['widest_venue']} ({spread_summary['widest_ccy']}))")
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
