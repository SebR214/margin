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


def main():
    if requests is None:
        sys.exit("pip install requests")

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = build_rows(ts, CORRIDORS["SGD->PHP"])

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
