#!/usr/bin/env python3
"""Every Binance P2P ad, not the first 10 (SEB-311 step 1). Collected, stored, published nowhere.

collector_p2p.py asks for 10 ads a side and writes the median of them, so data/p2p_sides.csv always says 10 and a market where
the sellers are leaving looks the same as a busy one. This reads the same board, the same 53 currencies and both sides, page by
page, and writes every ad it gets to a sidecar:

    data/p2p_ads/YYYY-MM-DD.csv   (one file a day since 31 Oct; data/p2p_ads.csv, closed on 28 Oct, is never written again)
    ts_utc,ccy,side,rank,price,available,min_order,max_order,source_ok,error

One row per ad. side is what the person using the board does: "buy" is someone buying USDT for the local currency, as in
collector_p2p.py. rank counts from 1 in the order the board returns the ads (best price first). available is the ad's
tradable amount in USDT, min_order and max_order are its limits in the local currency. No amount filter is sent, so thin and
small ads are in, which is the point. The published median is not touched: collector_p2p.py, p2p_basis.csv and every reader of
them stay exactly as they were.

A board with no ads is one row with a blank rank and "no ads", source_ok true: an answer. A failed pull is one row with
source_ok false and the reason, never a gap and never a copy of the previous hour. The ts_utc is the run's own clock, whole
seconds, the same for every row of the run.

The cap: MAX_PAGES pages of PAGE_ROWS (20 is the server's own maximum), so at most 40 ads a side (a run of 60 ads a side wrote 369 KB
in an hour, 9 MB a day, which a repository does not carry for long). Thin markets, where thinning matters, come back whole; a deep
market is cut at 40 and its real depth is in data/p2p_depth.csv. A cap in time too: if the run
passes TIME_BUDGET_SECONDS the currencies not yet read are written as source_ok false rows saying so, and the run still exits 0
unless nothing at all was read. Binance is the only board read here: OKX's collector keeps its own file.

Usage:  python3 collector_p2p_ads.py             # one pass, appends to today's data/p2p_ads/ file
        python3 collector_p2p_ads.py --selftest   # parser and paging on fixtures, no network, writes nothing
"""
import csv
import datetime as dt
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
import daily_csv
NAME = "p2p_ads"                                   # data/p2p_ads/YYYY-MM-DD.csv, see tools/daily_csv.py
HEADER = ["ts_utc", "ccy", "side", "rank", "price", "available", "min_order", "max_order", "source_ok", "error"]
SEARCH_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
PAGE_ROWS = 20
MAX_PAGES = 2
TIME_BUDGET_SECONDS = 420
PAUSE = 0.15
TIMEOUT = 20
SIDES = (("buy", "BUY"), ("sell", "SELL"))


def body(ccy, trade_type, page):
    return {"page": page, "rows": PAGE_ROWS, "asset": "USDT", "fiat": ccy, "tradeType": trade_type,
            "payTypes": [], "publisherType": None}


def num(x):
    """A positive number from a string, or '' (a missing figure is a blank, not a zero)."""
    try:
        v = float(x)
        return v if v > 0 else ""
    except (TypeError, ValueError):
        return ""


def parse_page(payload):
    """One answer -> [(price, available, min_order, max_order)] in board order. Raises on an answer that is not a board."""
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("not an ad board answer")
    if str(payload.get("code")) not in ("000000", "None"):
        raise ValueError("board code %s" % payload.get("code"))
    out = []
    for row in payload.get("data") or []:
        adv = (row or {}).get("adv") or {}
        price = num(adv.get("price"))
        if price == "":
            continue                                   # an ad with no usable price is not an ad we can store
        out.append((price, num(adv.get("tradableQuantity")), num(adv.get("minSingleTransAmount")), num(adv.get("maxSingleTransAmount"))))
    return out


def read_side(ccy, trade_type, post):
    """All the ads (up to the cap) for one currency and side. Raises when a page cannot be read."""
    ads = []
    for page in range(1, MAX_PAGES + 1):
        got = parse_page(post(SEARCH_URL, body(ccy, trade_type, page)))
        ads.extend(got)
        if len(got) < PAGE_ROWS:
            break
    return ads


def rows_for(ts, ccy, post, now=time.time, deadline=None):
    """The rows of one currency, both sides. Never raises: a failure is a row."""
    out = []
    for side, trade_type in SIDES:
        if deadline is not None and now() > deadline:
            out.append([ts, ccy, side, "", "", "", "", "", False, "time budget used before this currency was read"])
            continue
        try:
            ads = read_side(ccy, trade_type, post)
        except Exception as e:
            out.append([ts, ccy, side, "", "", "", "", "", False, "%s:%s" % (type(e).__name__, str(e)[:80])])
            continue
        if not ads:
            out.append([ts, ccy, side, "", "", "", "", "", True, "no ads"])
        for i, (p, a, lo, hi) in enumerate(ads, 1):
            out.append([ts, ccy, side, i, p, a, lo, hi, True, ""])
    return out


def collect():
    import requests                                    # imported here so the offline self-test runs without it
    import collector_p2p                               # the same 53 currencies as the published board

    def post(url, b):
        time.sleep(PAUSE)
        r = requests.post(url, json=b, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        return r.json()

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    deadline = time.time() + TIME_BUDGET_SECONDS
    rows = []
    for ccy in collector_p2p.CURRENCIES:
        rows.extend(rows_for(ts, ccy, post, deadline=deadline))
    daily_csv.append(NAME, HEADER, rows)               # written before anything is printed
    ads = sum(1 for r in rows if r[3] != "")
    bad = sorted({r[1] for r in rows if r[8] is False})
    print("p2p_ads: %d ads from %d currencies, %d with a failed or skipped side%s" % (
        ads, len({r[1] for r in rows if r[3] != ""}), len(bad), (" (" + ", ".join(bad[:12]) + ")") if bad else ""))
    return 0 if ads else 1                             # nothing read at all fails loud


def _page(prices, code="000000"):
    return {"code": code, "data": [{"adv": {"price": str(p), "tradableQuantity": "100.5", "minSingleTransAmount": "50",
                                            "maxSingleTransAmount": "5000"}} for p in prices]}


def selftest():
    assert parse_page(_page([54.98, 55.1])) == [(54.98, 100.5, 50.0, 5000.0), (55.1, 100.5, 50.0, 5000.0)]
    assert parse_page({"code": "000000", "data": [{"adv": {"price": "x"}}, {"adv": {"price": "3"}}]}) == [(3.0, "", "", "")]
    for bad in (None, {"code": "000000"}, _page([1], code="100001")):
        try:
            parse_page(bad)
            raise AssertionError("a bad answer must raise")
        except ValueError:
            pass
    calls = []

    def post(url, b):                                   # a board of 30 ads: 20, 10
        calls.append(b["page"])
        return _page([10 + b["page"]] * {1: 20, 2: 10}.get(b["page"], 0))
    assert len(read_side("EGP", "BUY", post)) == 30 and calls == [1, 2], calls
    calls.clear()

    def deep(url, b):                                   # a deep board stops at the cap
        calls.append(b["page"])
        return _page([1] * 20)
    assert len(read_side("EGP", "BUY", deep)) == 20 * MAX_PAGES == 40 and calls == [1, 2], calls

    def thin(url, b):
        return _page([])
    r = rows_for("t", "BND", thin)
    assert [(x[2], x[3], x[8], x[9]) for x in r] == [("buy", "", True, "no ads"), ("sell", "", True, "no ads")], r

    def down(url, b):
        raise OSError("timeout")
    r = rows_for("t", "BND", down)
    assert all(x[8] is False and "OSError" in x[9] for x in r) and len(r) == 2, r
    r = rows_for("t", "BND", post, now=lambda: 10, deadline=5)
    assert all(x[8] is False and "time budget" in x[9] for x in r), r
    r = rows_for("t", "EGP", post)
    assert [x[3] for x in r if x[2] == "buy"] == list(range(1, 31)) and r[0][4] == 11.0, r[:2]
    print("collector_p2p_ads self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
