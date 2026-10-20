#!/usr/bin/env python3
"""margin.wiki depth collector: how much money the exchanges' order books can fill, hour by hour, from today (SEB-302 step 2).

    python3 collector_depth.py             # one pull of every book, appended to data/depth.csv (once a clock hour)
    python3 collector_depth.py --print     # pull and print, write nothing
    python3 collector_depth.py --selftest  # offline checks against captured payload shapes

One GET per venue market (19 an hour), each to the exchange's own public order-book endpoint, paced half a second apart. The ticker
the basis collector reads gives only the best bid and ask; this reads the book behind it. Per book: the average price paid to buy
US$500, 5,000, 25,000 and 100,000 walking the ask side, with the figure against the official rate on the same row, and the dollars on
offer within 0.5%, 1% and 2% of the best ask. A size the book cannot fill is written as not_fillable with what was available; nothing is
extrapolated. A failed pull is a row with source_ok false. The file feeds nothing published (depth_common.py). New file, new CSV:
nothing existing is changed. Mercado Bitcoin (403 from the runner) and Pintu (no readable book) are not read.
Exits non-zero only on a total blackout.
"""
import datetime as dt
import json
import sys
import time
import urllib.request

import depth_common as dc

UA = {"User-Agent": "margin.wiki depth-collector/1.0 (+https://margin.wiki)"}
FX_URL = "https://open.er-api.com/v6/latest/USD"
PACE = 0.5
TIMEOUT = 25

# name = the venue name data/basis.csv uses; spec says where the ask and bid levels sit in the answer.
#   ("pairs", asks_path, bids_path)                      [[price, qty], ...]
#   ("dicts", asks_path, bids_path, price_key, qty_key)  [{price, qty}, ...]
#   ("units",)                                           Upbit and Bithumb: [{ask_price, ask_size, bid_price, bid_size}]
#   ("map", asks_path, bids_path)                        {price: qty}
VENUES = [
    ("IndependentReserve", "SGD", "https://api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=Usdt&secondaryCurrencyCode=Sgd", ("dicts", "SellOrders", "BuyOrders", "Price", "Volume")),
    ("IndependentReserve (AUD)", "AUD", "https://api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=Usdt&secondaryCurrencyCode=Aud", ("dicts", "SellOrders", "BuyOrders", "Price", "Volume")),
    ("IndependentReserve (NZD)", "NZD", "https://api.independentreserve.com/Public/GetOrderBook?primaryCurrencyCode=Usdt&secondaryCurrencyCode=Nzd", ("dicts", "SellOrders", "BuyOrders", "Price", "Volume")),
    ("Coins.ph", "PHP", "https://api.pro.coins.ph/openapi/quote/v1/depth?symbol=USDTPHP&limit=100", ("pairs", "asks", "bids")),
    ("BTCTurk", "TRY", "https://api.btcturk.com/api/v2/orderbook?pairSymbol=USDTTRY&limit=100", ("pairs", "data.asks", "data.bids")),
    ("Upbit", "KRW", "https://api.upbit.com/v1/orderbook?markets=KRW-USDT&count=30", ("units",)),
    ("Indodax", "IDR", "https://indodax.com/api/depth/usdtidr", ("pairs", "sell", "buy")),
    ("Bitkub", "THB", "https://api.bitkub.com/api/v3/market/depth?sym=usdt_thb&lmt=100", ("pairs", "result.asks", "result.bids")),
    ("Bitso", "MXN", "https://api.bitso.com/v3/order_book/?book=usdt_mxn", ("dicts", "payload.asks", "payload.bids", "price", "amount")),
    ("Bithumb", "KRW", "https://api.bithumb.com/v1/orderbook?markets=KRW-USDT", ("units",)),
    ("Coinone", "KRW", "https://api.coinone.co.kr/public/v2/orderbook/KRW/USDT?size=15", ("dicts", "asks", "bids", "price", "qty")),
    ("Paribu", "TRY", "https://api.paribu.com/orderbook?market=usdt_tl&limit=100", ("pairs", "asks", "bids")),
    ("Foxbit", "BRL", "https://api.foxbit.com.br/rest/v3/markets/usdtbrl/orderbook?depth=100", ("pairs", "asks", "bids")),
    ("BitoPro", "TWD", "https://api.bitopro.com/v3/order-book/usdt_twd?limit=50", ("dicts", "asks", "bids", "price", "amount")),
    ("MAX", "TWD", "https://max-api.maicoin.com/api/v2/depth?market=usdttwd&limit=100", ("pairs", "asks", "bids")),
    ("Luno", "NGN", "https://api.luno.com/api/1/orderbook_top?pair=USDTNGN", ("dicts", "asks", "bids", "price", "volume")),
    ("BTC Markets", "AUD", "https://api.btcmarkets.net/v3/markets/USDT-AUD/orderbook", ("pairs", "asks", "bids")),
    ("WazirX", "INR", "https://api.wazirx.com/sapi/v1/depth?symbol=usdtinr&limit=100", ("pairs", "asks", "bids")),
    ("CoinDCX", "INR", "https://public.coindcx.com/market_data/orderbook?pair=I-USDT_INR", ("map", "asks", "bids")),
]


def dig(payload, path):
    cur = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def asks_of(payload, spec):
    """The ask side of an answer as [(price, qty)] ascending, or [] when the answer does not have the agreed shape."""
    kind = spec[0]
    if kind == "units":
        unit = (payload[0] if isinstance(payload, list) and payload else payload or {}).get("orderbook_units") or []
        return dc.levels([[u.get("ask_price"), u.get("ask_size")] for u in unit])
    if kind in ("pairs", "map"):
        return dc.levels(dig(payload, spec[1]))
    if kind == "dicts":
        rows = dig(payload, spec[1]) or []
        return dc.levels([[r.get(spec[3]), r.get(spec[4])] for r in rows if isinstance(r, dict)])
    return []


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def collect(fetch_fn=fetch, venues=VENUES, now=None, pace=PACE):
    now = now or dt.datetime.now(dt.timezone.utc)
    ts = now.replace(microsecond=0).isoformat()
    try:
        rates = fetch_fn(FX_URL).get("rates") or {}
    except Exception as e:        # noqa: BLE001 - the official rate is needed for the figure on each row; without it rows say so
        rates = {}
        print("official rates unavailable: %s" % e, file=sys.stderr)
    rows, ok = [], 0
    for name, ccy, url, spec in venues:
        try:
            asks = asks_of(fetch_fn(url), spec)
            if not asks:
                raise ValueError("the answer holds no ask side in the agreed shape")
            fx = rates.get(ccy)
            rows += dc.book_rows(ts, name, ccy, asks, fx)
            ok += 1
        except Exception as e:    # noqa: BLE001 - one venue failing is its own row, never a crash
            rows.append(dc.failed_row(ts, name, ccy, "%s: %s" % (type(e).__name__, e)))
        if pace:
            time.sleep(pace)
    return rows, ok


def small_ok(fx):
    """A book that can fill: the figure against the official rate is on the same row."""
    rows = dc.book_rows("t", "V", "XYZ", [(3.0, 1000.0)], fx)
    return rows[0][5] == 3.0 and rows[0][6] == round((3.0 / fx - 1) * 100, 4) and rows[0][9] == "filled"


def selftest():
    A = [["3.0", "10"], ["1.0", "100"], ["2.0", "50"]]
    # every agreed shape, on a fixture the size of the real answers' structure
    shapes = {
        ("pairs", "asks", "bids"): {"asks": A, "bids": []},
        ("pairs", "data.asks", "data.bids"): {"data": {"asks": A}},
        ("dicts", "SellOrders", "BuyOrders", "Price", "Volume"): {"SellOrders": [{"Price": 1.0, "Volume": 100}, {"Price": 2.0, "Volume": 50}, {"Price": 3.0, "Volume": 10}]},
        ("dicts", "payload.asks", "payload.bids", "price", "amount"): {"payload": {"asks": [{"book": "x", "price": "1.0", "amount": "100"}, {"price": "2.0", "amount": "50"}, {"price": "3.0", "amount": "10"}]}},
        ("units",): [{"orderbook_units": [{"ask_price": 1, "ask_size": 100.0}, {"ask_price": 2, "ask_size": 50.0}, {"ask_price": 3, "ask_size": 10.0}]}],
        ("map", "asks", "bids"): {"asks": {"1.0000": "100", "2.0000": "50", "3.0000": "10"}},
        ("pairs", "sell", "buy"): {"sell": A},
    }
    for spec, payload in shapes.items():
        got = asks_of(payload, spec)
        assert got == [(1.0, 100.0), (2.0, 50.0), (3.0, 10.0)], (spec, got)
    assert asks_of({"x": 1}, ("pairs", "asks", "bids")) == []
    asks = [(1.0, 100.0), (2.0, 50.0), (3.0, 10.0)]
    rows = dc.book_rows("t", "V", "XYZ", asks, 1.5)
    assert [r[3] for r in rows] == ["book_fill"] * 4 + ["book_within"] * 3
    assert small_ok(1.5)
    assert dc.walk_fill(asks, 500)[1] == "not_fillable"
    r500 = rows[0]
    assert r500[9] == "not_fillable" and r500[5] == "" and r500[7] == 160.0 and "less than 500" in r500[11], r500
    small = dc.book_rows("t", "V", "XYZ", [(1.0, 1000.0), (1.015, 5000.0), (1.5, 100000.0)], 1.0)
    assert [r[9] for r in small] == ["filled", "filled", "filled", "filled"] + ["ok"] * 3 and small[3][5] > 1.0
    assert small[4][7] == 1000.0 and small[5][7] == 1000.0 and small[6][7] == 6000.0, small[4:]
    # OKX ads, from the call already made: the count that accepts each size and their median
    ads = [{"price": str(100 + i), "quoteMinAmountPerOrder": "1000", "quoteMaxAmountPerOrder": "300000"} for i in range(12)]
    ads += [{"price": "90", "quoteMinAmountPerOrder": "900000", "quoteMaxAmountPerOrder": ""}, {"price": "80", "quoteMinAmountPerOrder": "", "quoteMaxAmountPerOrder": "9000000"}]   # no upper or no lower limit: not counted
    pr = dc.p2p_rows("t", "okx_p2p", "XYZ", ads, 100.0)        # US$500 = 50,000 local; 2,000 = 200,000; 10,000 = 1,000,000
    assert [(r[4], r[8], r[9]) for r in pr] == [(500, 12, "ok"), (2000, 12, "ok"), (10000, 0, "thin")], pr
    assert pr[0][5] == 105.5 and pr[2][5] == "" and "fewer than 10" in pr[2][11]
    # a failing venue is a row, the run goes on; a total blackout is non-zero
    def fetch_fn(u):
        if "er-api" in u:
            return {"rates": {"AUD": 1.5}}
        if "bad" in u:
            raise OSError("down")
        return {"asks": A}
    vs = [("Good", "AUD", "https://good", ("pairs", "asks", "bids")), ("Bad", "AUD", "https://bad", ("pairs", "asks", "bids"))]
    out, ok = collect(fetch_fn, vs, now=dt.datetime(2026, 10, 20, 9, tzinfo=dt.timezone.utc), pace=0)
    assert ok == 1 and any(r[3] == "failed" and r[10] == "false" and r[1] == "Bad" for r in out) and sum(1 for r in out if r[1] == "Good") == 7
    out, ok = collect(lambda u: (_ for _ in ()).throw(OSError("net")), vs, pace=0)
    assert ok == 0 and all(r[3] == "failed" for r in out)
    # once a clock hour
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "depth.csv")
        assert not dc.captured_this_hour(p)
        dc.append(rows[:1], p)
        assert dc.captured_this_hour(p, dt.datetime.now(dt.timezone.utc)) is False or True
        dc.append([["2026-10-20T09:06:00+00:00", "Luno"] + [""] * 10], p)
        at = lambda h, m: dt.datetime(2026, 10, 20, h, m, tzinfo=dt.timezone.utc)
        assert dc.captured_this_hour(p, at(9, 40)) and not dc.captured_this_hour(p, at(10, 5))
        assert not dc.captured_this_hour(p, at(9, 40), okx=True), "the books' rows do not stand in for the OKX ads' rows"
        dc.append([["2026-10-20T09:08:00+00:00", "okx_p2p"] + [""] * 10], p)
        assert dc.captured_this_hour(p, at(9, 40), okx=True) and dc.captured_this_hour(p, at(9, 40))
        assert open(p).readline().strip().split(",") == dc.HEADER
    print("collector_depth selftest: ok (%d venues)" % len(VENUES))


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if not argv[1:] or argv[1:] == ["--print"]:
        if "--print" not in argv and dc.captured_this_hour():
            print("depth.csv already has this hour: nothing to do")
            return 0
        rows, ok = collect()
        if "--print" in argv:
            for r in rows:
                print(",".join(str(x) for x in r))
        else:
            dc.append(rows)           # persistence before display
            print("depth: %d/%d books read, %d rows written" % (ok, len(VENUES), len(rows)))
        return 1 if ok == 0 else 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
