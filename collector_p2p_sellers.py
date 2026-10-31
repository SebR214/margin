#!/usr/bin/env python3
"""Who sells: a stable, hashed seller id for every P2P ad (SEB-384 step 1). Collected, stored, published nowhere.

data/p2p_ads.csv holds the price, amount and limits of each Binance ad but not the seller. The seller cannot be recovered later,
so this stores it now, in a sidecar:

    data/p2p_ads_sellers/YYYY-MM-DD.csv   (one file a day since 31 Oct; data/p2p_ads_sellers.csv, closed on 28 Oct, is never written again)
    ts_utc,read_utc,board,ccy,side,rank,seller_id,price,completion_rate,order_count,merchant_flag,source_ok,error

ts_utc, ccy, side and rank are the keys of data/p2p_ads.csv: ts_utc is that file's newest run (this runs right after
collector_p2p_ads.py), side means the same, rank counts from 1 in the order the board returns the ads. The board is read again, so
a book that moved in between can shift a rank; price is stored so a join can be checked against the same row of p2p_ads.csv, and
read_utc is this run's own clock. The same two pages a side are read (at most 40 ads, as there).

seller_id is the first 16 hex characters of SHA-256 over "board:advertiser id". The raw id and nickname are never written.
completion_rate is the board's own figure (a fraction, 0 to 1): Binance monthFinishRate, OKX completedRate. order_count is the
board's own count: Binance monthOrderCount (the last 30 days), OKX completedOrderQuantity (completed orders). merchant_flag is
True when the board marks the seller a merchant: Binance userType "merchant", OKX creatorType other than "common".

board is "binance" or "okx". OKX ads are not in p2p_ads.csv (collector_p2p_okx.py keeps a median only), so its rows have no row there
to join; they carry their own rank in the book's order. OKX's side is the books side parameter, as in collector_p2p_okx.py.

A board with no ads is one row with a blank rank and "no ads", source_ok true. A failed pull is one row with source_ok false and the
reason, never a gap. The run exits non-zero if no ad at all was read.

Usage:  python3 collector_p2p_sellers.py             # one pass, appends to today's data/p2p_ads_sellers/ file
        python3 collector_p2p_sellers.py --selftest   # parsers on fixtures, no network, writes nothing
"""
import csv
import datetime as dt
import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
import daily_csv
NAME = "p2p_ads_sellers"                            # data/p2p_ads_sellers/YYYY-MM-DD.csv, see tools/daily_csv.py
ADS = "p2p_ads"                                     # read with the old file and the day files together
HEADER = ["ts_utc", "read_utc", "board", "ccy", "side", "rank", "seller_id", "price", "completion_rate", "order_count",
          "merchant_flag", "source_ok", "error"]
BINANCE_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
OKX_URL = "https://www.okx.com/v3/c2c/tradingOrders/books"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
PAGE_ROWS = 20
MAX_PAGES = 2
MAX_ADS = PAGE_ROWS * MAX_PAGES
TIME_BUDGET_SECONDS = 300           # per board
PAUSE = 0.15
TIMEOUT = 20
TAIL_BYTES = 8192
SIDES = (("buy", "BUY"), ("sell", "SELL"))


def seller_id(board, raw):
    """16 hex characters, or '' when the board gave no id. The raw id never leaves this function."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(("%s:%s" % (board, raw)).encode("utf-8")).hexdigest()[:16]


def num(x):
    try:
        v = float(x)
        return v if v >= 0 else ""
    except (TypeError, ValueError):
        return ""


def price_of(x):
    v = num(x)
    return v if v != "" and v > 0 else ""


def parse_binance(payload):
    """One board answer -> [(seller_id, price, completion_rate, order_count, merchant_flag)] in board order."""
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("not an ad board answer")
    if str(payload.get("code")) not in ("000000", "None"):
        raise ValueError("board code %s" % payload.get("code"))
    out = []
    for row in payload.get("data") or []:
        adv, who = (row or {}).get("adv") or {}, (row or {}).get("advertiser") or {}
        p = price_of(adv.get("price"))
        if p == "":
            continue                                   # the same ads p2p_ads.csv skips, so ranks line up
        out.append((seller_id("binance", who.get("userNo")), p, num(who.get("monthFinishRate")), num(who.get("monthOrderCount")),
                    str(who.get("userType") or "").lower() == "merchant"))
    return out


def parse_okx(payload, side):
    """OKX books answer -> the same tuples for one side. The whole book comes back whatever the page size; it is cut at MAX_ADS."""
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(payload.get("code")) != "0" or side not in data:
        raise ValueError("not an OKX book answer")
    out = []
    for a in data[side] or []:
        p = price_of(a.get("price"))
        if p == "":
            continue
        out.append((seller_id("okx", a.get("merchantId")), p, num(a.get("completedRate")), num(a.get("completedOrderQuantity")),
                    str(a.get("creatorType") or "common").lower() != "common"))
    return out[:MAX_ADS]


def read_binance(ccy, trade_type, post):
    ads = []
    for page in range(1, MAX_PAGES + 1):
        got = parse_binance(post(BINANCE_URL, {"page": page, "rows": PAGE_ROWS, "asset": "USDT", "fiat": ccy,
                                               "tradeType": trade_type, "payTypes": [], "publisherType": None}))
        ads.extend(got)
        if len(got) < PAGE_ROWS:
            break
    return ads


def read_okx(ccy, side, get):
    url = "%s?side=%s&paymentMethod=all&userType=all&baseCurrency=usdt&quoteCurrency=%s&currentPage=1&numberPerPage=%d" % (
        OKX_URL, side, ccy.lower(), PAGE_ROWS)
    return parse_okx(get(url), side)


def rows_for(ts, read_utc, board, ccy, reader, now=time.time, deadline=None):
    """The rows of one currency on one board, both sides. reader(side, trade_type) -> ads. Never raises: a failure is a row."""
    out = []
    for side, trade_type in SIDES:
        if deadline is not None and now() > deadline:
            out.append([ts, read_utc, board, ccy, side, "", "", "", "", "", "", False, "time budget used before this currency was read"])
            continue
        try:
            ads = reader(side, trade_type)
        except Exception as e:
            out.append([ts, read_utc, board, ccy, side, "", "", "", "", "", "", False, "%s:%s" % (type(e).__name__, str(e)[:80])])
            continue
        if not ads:
            out.append([ts, read_utc, board, ccy, side, "", "", "", "", "", "", True, "no ads"])
        for i, (sid, p, rate, orders, merchant) in enumerate(ads, 1):
            out.append([ts, read_utc, board, ccy, side, i, sid, p, rate, orders, merchant, sid != "", "" if sid else "no seller id"])
    return out


def newest_ads_ts(name=ADS, data=daily_csv.DATA):
    """The ts_utc of the newest run in p2p_ads (today's file, else the newest before it, else the closed p2p_ads.csv), from the
    tail of that file; None if there is none."""
    lines = daily_csv.tail(name, TAIL_BYTES, data)
    stamps = [ln.split(",", 1)[0] for ln in lines if ln[:2] == "20" and ln.count(",") >= 9]
    return max(stamps) if stamps else None


def collect():
    import requests                                    # imported here so the offline self-test runs without it
    import collector_p2p                               # the same currencies as the published board

    def post(url, b):
        time.sleep(PAUSE)
        r = requests.post(url, json=b, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        return r.json()

    def get(url):
        time.sleep(PAUSE)
        r = requests.get(url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        return r.json()

    read_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts = newest_ads_ts() or read_utc
    rows = []
    t0 = time.time()
    for ccy in collector_p2p.CURRENCIES:
        rows.extend(rows_for(ts, read_utc, "binance", ccy, lambda s, t, c=ccy: read_binance(c, t, post), deadline=t0 + TIME_BUDGET_SECONDS))
    t1 = time.time()
    for ccy in collector_p2p.CURRENCIES:
        rows.extend(rows_for(ts, read_utc, "okx", ccy, lambda s, t, c=ccy: read_okx(c, s, get), deadline=t1 + TIME_BUDGET_SECONDS))
    daily_csv.append(NAME, HEADER, rows)               # written before anything is printed
    for board in ("binance", "okx"):
        got = [r for r in rows if r[2] == board and r[5] != ""]
        bad = sorted({r[3] for r in rows if r[2] == board and r[11] is False})
        print("p2p_sellers %s: %d ads from %d currencies, %d with a failed or skipped side%s" % (
            board, len(got), len({r[3] for r in got}), len(bad), (" (" + ", ".join(bad[:12]) + ")") if bad else ""))
    return 0 if any(r[5] != "" for r in rows) else 1   # nothing read at all fails loud


def _binance(prices, ids=None):
    return {"code": "000000", "data": [{"adv": {"price": str(p)}, "advertiser": {
        "userNo": (ids or {}).get(i, "u%d" % i), "monthFinishRate": 0.95, "monthOrderCount": 40 + i,
        "userType": "merchant" if i == 0 else "user"}} for i, p in enumerate(prices)]}


def _okx(prices, side="buy"):
    return {"code": 0, "data": {side: [{"price": str(p), "merchantId": "m%d" % i, "completedRate": "0.9900",
                                         "completedOrderQuantity": 100 + i, "creatorType": "common" if i % 2 else "diamond"}
                                        for i, p in enumerate(prices)]}}


def selftest():
    a = seller_id("binance", "abc")
    assert len(a) == 16 and all(c in "0123456789abcdef" for c in a) and a == seller_id("binance", "abc"), a
    assert a != seller_id("okx", "abc") and seller_id("binance", "") == "" and seller_id("binance", None) == ""
    got = parse_binance(_binance([54.98, 55.1]))
    assert [(x[1], x[2], x[3], x[4]) for x in got] == [(54.98, 0.95, 40.0, True), (55.1, 0.95, 41.0, False)], got
    assert got[0][0] == seller_id("binance", "u0") and "u0" not in str(got)
    assert [x[1] for x in parse_binance({"code": "000000", "data": [{"adv": {"price": "x"}}, {"adv": {"price": "3"}, "advertiser": {}}]})] == [3.0]
    for bad in (None, {"code": "000000"}, _binance([1]) | {"code": "100001"}):
        try:
            parse_binance(bad)
            raise AssertionError("a bad answer must raise")
        except ValueError:
            pass
    o = parse_okx(_okx([50.9, 50.8, 50.7]), "buy")
    assert [(x[1], x[2], x[3], x[4]) for x in o] == [(50.9, 0.99, 100.0, True), (50.8, 0.99, 101.0, False), (50.7, 0.99, 102.0, True)], o
    assert len(parse_okx(_okx([1.0] * 90), "buy")) == MAX_ADS
    for bad in (None, {"code": 0, "data": {}}, {"code": 7, "data": {"buy": []}}):
        try:
            parse_okx(bad, "buy")
            raise AssertionError("a bad OKX answer must raise")
        except ValueError:
            pass
    calls = []

    def post(url, b):                                   # a board of 30 ads: 20, 10
        calls.append(b["page"])
        return _binance([10 + b["page"]] * {1: 20, 2: 10}.get(b["page"], 0))
    r = rows_for("T", "R", "binance", "EGP", lambda s, t: read_binance("EGP", t, post))
    assert [x[5] for x in r if x[4] == "buy"] == list(range(1, 31)) and calls == [1, 2, 1, 2], (calls, r[:1])
    assert all(x[0] == "T" and x[1] == "R" and x[11] is True for x in r) and len(r[0]) == len(HEADER)

    def thin(s, t):
        return []
    r = rows_for("T", "R", "okx", "BND", thin)
    assert [(x[4], x[5], x[11], x[12]) for x in r] == [("buy", "", True, "no ads"), ("sell", "", True, "no ads")], r

    def down(s, t):
        raise OSError("timeout")
    r = rows_for("T", "R", "okx", "BND", down)
    assert len(r) == 2 and all(x[11] is False and "OSError" in x[12] for x in r), r
    r = rows_for("T", "R", "okx", "BND", thin, now=lambda: 10, deadline=5)
    assert all(x[11] is False and "time budget" in x[12] for x in r), r
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        head = "ts_utc,ccy,side,rank,price,available,min_order,max_order,source_ok,error\n"
        assert newest_ads_ts("p2p_ads", tmp) is None
        with open(os.path.join(tmp, "p2p_ads.csv"), "w") as f:            # the closed file, read when no day file exists
            f.write(head + "2026-10-24T07:00:00Z,AED,buy,1,3.6,1,1,1,True,\n2026-10-24T08:00:00Z,AED,buy,1,3.6,1,1,1,True,\n")
        assert newest_ads_ts("p2p_ads", tmp) == "2026-10-24T08:00:00Z"
        os.makedirs(os.path.join(tmp, "p2p_ads"))
        with open(os.path.join(tmp, "p2p_ads", "2026-10-31.csv"), "w") as f:  # a day file wins over the closed one
            f.write(head + "2026-10-31T01:00:00Z,AED,buy,1,3.6,1,1,1,True,\n")
        assert newest_ads_ts("p2p_ads", tmp) == "2026-10-31T01:00:00Z"
    print("collector_p2p_sellers self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
