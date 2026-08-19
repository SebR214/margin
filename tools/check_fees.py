#!/usr/bin/env python3
"""Fee drift watcher for the corridor config.

Fees are the largest single term in the taker decomposition and the only major
input with no staleness signal. Both schedules were verified once, by hand, on
2026-08-10 -- and that verification found two live errors and killed the site's
original headline finding. Nothing has re-checked them since.

So: re-read both venues' published fee pages monthly, diff the base tier against
the constants in collector.py, and go red on any drift. This job never *fixes* a
number. It reports. A silently corrected fee is the exact failure mode the check
exists to prevent -- a human decides what the new number is.

Every outcome is a row, including the failures. A parse that breaks writes
status=parse_fail with the reason and still exits non-zero; a check that leaves
no trace is indistinguishable from a check that never ran.

Exit 0 = every row this run is ok. Exit 1 = any mismatch or any parse failure.
"""

import csv
import datetime as dt
import html
import os
import re
import sys

try:
    import requests
except ImportError:
    requests = None

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

# The constants under test. Imported, never re-declared -- a watcher that keeps
# its own copy of the number it is checking is checking itself.
from collector import CORRIDORS  # noqa: E402

CHECKS = os.path.join(HERE, "data", "fee_checks.csv")
FIELDS = [
    "ts_utc", "venue", "leg", "regime", "config_bps", "published_bps",
    "status", "source_url", "error",
]

HTTP_TIMEOUT = 20
UA = {"User-Agent": "margin.wiki fee-watcher/1.0 (+https://margin.wiki)"}

IR_URL = "https://www.independentreserve.com/fees"
# Bare domain in the spec; this is the article that actually carries the table.
COINS_URL = ("https://support.coins.ph/hc/en-us/articles/11620285112217-How-are-"
             "my-trading-fees-calculated-based-on-the-VIP-level-setup")
# Bitso publishes its own schedule as JSON -- no scraping, no parser to rot.
BITSO_URL = "https://api.bitso.com/v3/available_books/"
COINBASE_URL = "https://www.coinbase.com/advanced-fees"

# --- withdrawal (network) fees -------------------------------------------
# The network leg of a corridor is the SENDING venue's withdrawal fee, so these
# are what a route costs. Both pages below are public and state the number
# outright; Coinbase's is login-gated and is never scraped (see check_manual).
BITSO_WITHDRAW_URL = "https://bitso.com/fees/transactions"
IR_WITHDRAW_URL = "https://www.independentreserve.com/fees"
WITHDRAWALS = os.path.join(HERE, "data", "withdrawal_fees.csv")
WITHDRAWAL_FIELDS = [
    "ts_utc", "venue", "asset", "network", "fee_asset_units", "source_url",
    "source_ok",
]

# Coinbase's stable-pair schedule sits behind a login, so it cannot be read by a
# machine. Rather than pretend otherwise, the watcher puts the MANUAL
# verification on a clock: within this window the recorded date still counts,
# past it the row goes stale and the run goes red. The number is never invented
# and never repaired here -- a human re-reads the account and moves the date.
MANUAL_MAX_AGE_DAYS = 90


# ---------------------------------------------------------------- fetch/parse

def flatten(markup):
    """HTML -> one line of visible text. Enough to read a fee table, and it does
    not pull in a parser dependency for two pages."""
    txt = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    txt = html.unescape(re.sub(r"(?s)<[^>]+>", " ", txt))
    return re.sub(r"\s+", " ", txt).strip()


def fetch(url):
    """Return (text, resolved_url). Raises on any transport or HTTP error."""
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA, allow_redirects=True)
    r.raise_for_status()
    return flatten(r.text), r.url


def parse_ir(text):
    """Base tier of the Independent Reserve brokerage schedule, in bps.

    The table reads `AUD volume | Fees` with the base row keyed on volume 0 --
    i.e. 30-day volume below the first break at AUD 50,000. IR publishes no
    maker/taker split: one flat brokerage fee applies to both sides, so the
    caller uses this single number twice. If IR ever splits the two, this parser
    stops matching and the run goes red rather than guessing which is which.
    """
    m = re.search(r"AUD\s+volume\s+Fees\s+0\s+([\d.]+)\s*%\s+50,?000\s+[\d.]+\s*%",
                  text, re.I)
    if not m:
        raise ValueError("base-tier row (AUD volume 0) not found in fee table")
    return float(m.group(1)) * 100.0


def parse_coins(text):
    """VIP0 maker and taker from the Coins.ph Pro VIP table, in bps.

    Returns (taker_bps, maker_bps). The column order is read off the header
    rather than assumed -- the page currently prints Maker before Taker, which
    is the reverse of every other venue and exactly the kind of detail that
    silently inverts a fee schedule.
    """
    hdr = re.search(r"30-Day\s+Spot\s+Trading\s+Volume[^A-Za-z]*\(PHP\)\s+"
                    r"(Maker|Taker)\s+(Maker|Taker)", text, re.I)
    if not hdr:
        raise ValueError("VIP fee table header (Maker/Taker columns) not found")
    first, second = hdr.group(1).lower(), hdr.group(2).lower()
    if {first, second} != {"maker", "taker"}:
        raise ValueError(f"unexpected fee columns: {first}/{second}")

    row = re.search(r"VIP\s*0\b[^%]*?([\d.]+)\s*%\s*([\d.]+)\s*%", text, re.I)
    if not row:
        raise ValueError("VIP0 row not found in fee table")
    vals = {first: float(row.group(1)) * 100.0,
            second: float(row.group(2)) * 100.0}
    return vals["taker"], vals["maker"]


def fetch_json(url):
    """Return (payload, resolved_url). Raises on transport, HTTP or JSON error."""
    r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA, allow_redirects=True)
    r.raise_for_status()
    return r.json(), r.url


def parse_bitso(payload, book):
    """Base-tier maker/taker for one Bitso book, in bps. -> (taker_bps, maker_bps).

    Source is Bitso's own public API, so this reads a published number rather
    than scraping a rendered table: available_books returns, per book,
    fees.flat_rate {maker, taker} as decimal fractions ("0.006" = 0.60% = 60 bps).

    This is also what settles WHICH of Bitso's two published schedules governs
    usdt_mxn -- the API answers per book, so there is nothing to infer.
    """
    books = (payload or {}).get("payload")
    if not isinstance(books, list):
        raise ValueError("available_books payload missing or not a list")
    row = next((b for b in books if isinstance(b, dict) and b.get("book") == book), None)
    if row is None:
        raise ValueError(f"book {book} not present in available_books")
    flat = ((row.get("fees") or {}).get("flat_rate") or {})
    try:
        taker, maker = float(flat["taker"]), float(flat["maker"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"fees.flat_rate maker/taker missing for {book}")
    # Fractions, not percents: 0.0078 -> 78 bps. A schedule that ever arrives as
    # a percent would read 100x high and trip the mismatch, which is the point.
    return taker * 1e4, maker * 1e4


def parse_bitso_withdrawals(markup, asset="USDT"):
    """USDT withdrawal fee per network from bitso.com/fees/transactions, in
    ASSET UNITS (not bps). -> {network: fee}.

    The page carries two tables with the same row shape. Deposit rows read
    "... - Tron Network10 Confirmations | Free of charge"; withdrawal rows read
    "... - Tron Network* | 3.4 USDT". Only rows whose value parses as a number
    of the asset are taken, so a "Free of charge" DEPOSIT row can never be
    mistaken for a zero-cost withdrawal.
    """
    out = {}
    rows = re.findall(r'<tr><td class="left">(.*?)</td><td class="right">(.*?)</td></tr>',
                      markup, re.S)
    for label, value in rows:
        label = html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        value = html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
        if f"({asset})" not in label:
            continue
        net = re.search(r"-\s*([A-Za-z ]+?)\s*Network", label)
        amt = re.match(rf"^([\d.]+)\s*{asset}$", value)
        if not net or not amt:
            continue                     # deposit row, or a shape we do not know
        out[net.group(1).strip().lower()] = float(amt.group(1))
    if not out:
        raise ValueError(f"no {asset} withdrawal rows found in fee table")
    return out


def parse_ir_withdrawals(text, asset="USDT"):
    """USDT withdrawal fee per network from IR's fees page, in ASSET UNITS.

    The crypto table reads `Crypto | Network | Fees` with rows flattened to
    "Tether USD TRON 4.0 USDT". Anchored on the asset ticker at the end of the
    row so a neighbouring asset's row cannot bleed in.
    """
    out = {}
    for m in re.finditer(rf"Tether USD\s+([A-Za-z][A-Za-z0-9 ]*?)\s+([\d.]+)\s+{asset}\b",
                         text):
        out[m.group(1).strip().lower()] = float(m.group(2))
    if not out:
        raise ValueError(f"no Tether USD ({asset}) rows found in crypto withdrawal table")
    return out


# ---------------------------------------------------------------- rows

def clean(msg):
    """Error text safe for a naive comma-splitting CSV reader -- index.html has
    one, and a quoted field with a comma in it would shift every column. Commas
    and quotes both go, so the column never needs quoting in the first place."""
    txt = re.sub(r"\s+", " ", str(msg)).replace(",", ";").replace('"', "'")
    return txt.strip()[:200]


def check(ts, venue, leg, regime, config_bps, published_bps, url, error):
    """One diff -> one row. A missing published value is a parse failure; an
    unequal one is drift. Neither is ever repaired here."""
    if published_bps is None:
        return {"ts_utc": ts, "venue": venue, "leg": leg, "regime": regime,
                "config_bps": config_bps, "published_bps": "",
                "status": "parse_fail", "source_url": url,
                "error": clean(error or "no value parsed")}
    ok = abs(published_bps - config_bps) < 1e-6
    return {"ts_utc": ts, "venue": venue, "leg": leg, "regime": regime,
            "config_bps": config_bps, "published_bps": published_bps,
            "status": "ok" if ok else "mismatch", "source_url": url,
            "error": "" if ok else clean(
                f"config {config_bps} bps != published {published_bps} bps")}


def check_manual(ts, venue, leg, regime, config_bps, verified, url, now=None):
    """A schedule that cannot be read by a machine, checked against its clock.

    There is no published value to diff, so `published_bps` stays EMPTY --
    writing the config value back into that column would manufacture a
    confirmation the watcher never obtained. What is actually verified here is
    the age of the human verification: fresh -> ok, stale or unparseable -> a
    row and a non-zero exit, same as any other failure.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    row = {"ts_utc": ts, "venue": venue, "leg": leg, "regime": regime,
           "config_bps": config_bps, "published_bps": "",
           "source_url": url}
    try:
        seen = dt.datetime.strptime((verified or "").strip(), "%Y-%m-%d").replace(
            tzinfo=dt.timezone.utc)
    except ValueError:
        row.update(status="stale", error=clean(
            f"no usable verified date ({verified!r}); login-gated, verify by hand"))
        return row
    age = (now - seen).days
    if age > MANUAL_MAX_AGE_DAYS:
        row.update(status="stale", error=clean(
            f"manual verification {age}d old (limit {MANUAL_MAX_AGE_DAYS}d); "
            f"login-gated, re-read the account and update `verified`"))
    else:
        row.update(status="ok", error=clean(
            f"not scrapable (login-gated); manual verification {age}d old, "
            f"limit {MANUAL_MAX_AGE_DAYS}d"))
    return row


def append(rows):
    os.makedirs(os.path.dirname(CHECKS), exist_ok=True)
    new = not os.path.exists(CHECKS) or os.path.getsize(CHECKS) == 0
    with open(CHECKS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)
    return CHECKS


def build_rows(ts, cfg):
    on, off = cfg["onramp"], cfg["offramp"]

    # On-ramp: Independent Reserve, one flat rate standing in for both regimes.
    ir_bps, ir_url, ir_err = None, IR_URL, None
    try:
        text, ir_url = fetch(IR_URL)
        ir_bps = parse_ir(text)
    except Exception as e:
        ir_err = f"{type(e).__name__}: {e}"

    # Off-ramp: Coins.ph Pro VIP0, a genuine maker/taker split.
    ct_bps = cm_bps = None
    coins_url, coins_err = COINS_URL, None
    try:
        text, coins_url = fetch(COINS_URL)
        ct_bps, cm_bps = parse_coins(text)
    except Exception as e:
        coins_err = f"{type(e).__name__}: {e}"

    # Order fixed by the spec: on taker, on maker, off taker, off maker.
    return [
        check(ts, on["venue"], "onramp", "taker",
              float(on["taker_bps"]), ir_bps, ir_url, ir_err),
        check(ts, on["venue"], "onramp", "maker",
              float(on["maker_bps"]), ir_bps, ir_url, ir_err),
        check(ts, off["venue"], "offramp", "taker",
              float(off["taker_bps"]), ct_bps, coins_url, coins_err),
        check(ts, off["venue"], "offramp", "maker",
              float(off["maker_bps"]), cm_bps, coins_url, coins_err),
    ]


def load_withdrawals():
    """Recorded withdrawal rows. Missing file -> no rows, and the caller says so."""
    if not os.path.exists(WITHDRAWALS):
        return []
    with open(WITHDRAWALS, newline="") as f:
        return list(csv.DictReader(f))


def build_rows_withdrawals(ts):
    """Re-read each measured withdrawal fee and diff it against the recorded row.

    Reuses the frozen fee_checks.csv schema, so the columns carry a documented
    convention rather than a new file: `leg` is "withdrawal", `regime` is the
    NETWORK, and config/published hold ASSET UNITS (USDT), not bps -- there is
    no notional here to express a flat chain fee against.

    Coinbase rows are skipped on purpose: that schedule is login-gated and is
    never scraped. Its staleness is already covered by the 90-day manual clock.
    """
    recorded = [r for r in load_withdrawals()
                if (r.get("source_ok") or "").strip() == "True"]
    if not recorded:
        return []

    live, errs = {}, {}
    try:
        r = requests.get(BITSO_WITHDRAW_URL, timeout=HTTP_TIMEOUT, headers=UA,
                         allow_redirects=True)
        r.raise_for_status()
        live["bitso"] = (parse_bitso_withdrawals(r.text), r.url)
    except Exception as e:
        errs["bitso"] = f"{type(e).__name__}: {e}"
    try:
        text, url = fetch(IR_WITHDRAW_URL)
        live["independentreserve"] = (parse_ir_withdrawals(text), url)
    except Exception as e:
        errs["independentreserve"] = f"{type(e).__name__}: {e}"

    out = []
    for row in recorded:
        venue, net = row.get("venue"), row.get("network")
        try:
            recorded_fee = float(row.get("fee_asset_units"))
        except (TypeError, ValueError):
            recorded_fee = None
        if venue in errs:
            out.append(check(ts, venue, "withdrawal", net, recorded_fee, None,
                             row.get("source_url"), errs[venue]))
            continue
        fees, url = live.get(venue, ({}, row.get("source_url")))
        published = fees.get(net)
        err = None if published is not None else (
            f"network {net} no longer listed for {venue}")
        out.append(check(ts, venue, "withdrawal", net, recorded_fee, published,
                         url, err))
    return out


def build_rows_usdmxn(ts, cfg, now=None):
    """Corridor 2. Bitso is machine-readable; Coinbase is not."""
    on, off = cfg["onramp"], cfg["offramp"]

    # Off-ramp: Bitso usdt_mxn base tier, straight from Bitso's own API.
    bt_bps = bm_bps = None
    bitso_url, bitso_err = BITSO_URL, None
    try:
        payload, bitso_url = fetch_json(BITSO_URL)
        bt_bps, bm_bps = parse_bitso(payload, off["symbol"])
    except Exception as e:
        bitso_err = f"{type(e).__name__}: {e}"

    # On-ramp: Coinbase Advanced stable-pair fees are behind a login. Not
    # scraped, not guessed -- the manual verification is put on a clock instead.
    return [
        check_manual(ts, on["venue"], "onramp", "taker",
                     float(on["taker_bps"]), on.get("verified"), COINBASE_URL, now),
        check_manual(ts, on["venue"], "onramp", "maker",
                     float(on["maker_bps"]), on.get("verified"), COINBASE_URL, now),
        check(ts, off["venue"], "offramp", "taker",
              float(off["taker_bps"]), bt_bps, bitso_url, bitso_err),
        check(ts, off["venue"], "offramp", "maker",
              float(off["maker_bps"]), bm_bps, bitso_url, bitso_err),
    ]


def main():
    if requests is None:
        sys.exit("pip install requests")

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = build_rows(ts, CORRIDORS["SGD->PHP"])
    rows += build_rows_usdmxn(ts, CORRIDORS["USD->MXN"])
    rows += build_rows_withdrawals(ts)

    # Persist before display. Always -- the row is the evidence, and the print
    # below is only a convenience for whoever is reading the log.
    append(rows)

    for r in rows:
        pub = r["published_bps"]
        pub = f"{pub} bps" if pub != "" else "—"
        print(f"  [{r['status']:>10}] {r['venue']} {r['leg']} {r['regime']}: "
              f"config {r['config_bps']} bps vs published {pub}"
              + (f" -- {r['error']}" if r["error"] else ""))

    bad = [r for r in rows if r["status"] != "ok"]
    if bad:
        detail = "; ".join(f"{r['venue']}/{r['regime']} {r['status']}" for r in bad)
        print(f"\n  [error] fee drift or unreadable schedule -- {detail}",
              file=sys.stderr)
        print(f"  {len(bad)} of {len(rows)} checks failed; {len(rows)} rows "
              f"written to {os.path.relpath(CHECKS, HERE)}")
        sys.exit(1)

    print(f"  fees verified {ts} -- {len(rows)} checks ok, appended to "
          f"{os.path.relpath(CHECKS, HERE)}")


if __name__ == "__main__":
    main()
