"""One board x currency person-to-person collector, from a config block (SEB-422, lever 1, 31 Oct). No model.

A job adds one file, collectors/board_configs/<board>_<ccy>.json, and one test, tests/agent_board_<board>_<ccy>.py (see new_test()).
collector_boards.py reads every config once an hour and calls collect_config() for each.

    {"board": "bitget", "ccy": "NGN", "pair": "USDT", "endpoint": "https://www.bitget.com/v1/p2p/pub/adv/queryAdvList",
     "parser": "bitget", "min_ads": 5, "sides": {"buy": "1", "sell": "2"}, "extra": {}}

board   the name written in the tables; parser  the module in collectors/boards/; sides  the board's own word for "the reader buys
dollars" (buy) and "the reader sells them" (sell); min_ads  fewest usable ads a side needs before its median is a number; extra  what
one board needs and others do not (HTX's integer currency id).

What a run writes (nothing is written to an existing table's header; the daily tables are tools/daily_csv.py's):
  p2p_board_ads/<day>.csv    every ad read: ts_utc, board, ccy, side, rank, price, available, min_order, max_order, source_ok, error.
                             A new table because p2p_ads and p2p_offers have no board column and their readers assume Binance.
  p2p_ads_sellers/<day>.csv  one row per ad with the seller as a hash (collector_p2p_sellers.py's header and hash); the raw id is not kept.
  data/p2p_basis_boards.csv  one row an hour per config: ts_utc, board, ccy, buy_median, sell_median, n_ads, source_ok, error.
A usable ad takes an order of about 500 US dollars at its own price (the rule of collector_venue_common.py). A side with fewer usable
ads than min_ads, a median more than 30% from the official rate, or a pull that failed is a row with source_ok false and the reason.
Nothing here feeds a published number: a new board starts in quarantine in data/source_registry.json.
"""
import csv
import datetime as dt
import glob
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
import daily_csv  # noqa: E402
import collector_p2p_sellers as sellers  # noqa: E402
from collectors import boards  # noqa: E402

CONFIG_DIR = os.path.join(HERE, "collectors", "board_configs")
BASIS = os.path.join(HERE, "data", "p2p_basis_boards.csv")
BASIS_FIELDS = ["ts_utc", "board", "ccy", "buy_median", "sell_median", "n_ads", "source_ok", "error"]
ADS = "p2p_board_ads"
ADS_FIELDS = ["ts_utc", "board", "ccy", "side", "rank", "price", "available", "min_order", "max_order", "source_ok", "error"]
NOTIONAL = 500.0
BAND = 0.30
MAX_PAGES = 2
PAUSE = 0.4
TIMEOUT = 25
REQUIRED = ("board", "ccy", "pair", "parser", "min_ads", "sides")


def config_path(name):
    return os.path.join(CONFIG_DIR, name + ".json")


def load(path):
    with open(path) as f:
        cfg = json.load(f)
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise SystemExit("%s: config lacks %s" % (path, ", ".join(missing)))
    if set(cfg["sides"]) != {"buy", "sell"}:
        raise SystemExit("%s: sides must be exactly buy and sell" % path)
    return cfg


def load_all(config_dir=CONFIG_DIR):
    return [load(p) for p in sorted(glob.glob(os.path.join(config_dir, "*.json")))]


def official_rate(ccy, path=os.path.join(HERE, "data", "fx_rates.csv"), tail_bytes=4_000_000):
    """The newest official rate per US dollar for ccy in data/fx_rates.csv, or None. Reads only the end of the file."""
    if not os.path.exists(path):
        return None
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - tail_bytes))
        lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    best = None
    for r in csv.reader(lines):
        if len(r) >= 3 and r[1] == ccy:
            try:
                best = float(r[2])
            except ValueError:
                pass
    return best


def usable(ads):
    """Ads whose order limits take about 500 US dollars at their own price."""
    out = []
    for a in ads:
        p, lo, hi = a["price"], a["min_order"], a["max_order"]
        if (lo == "" or lo <= NOTIONAL * p) and (hi == "" or hi >= NOTIONAL * p):
            out.append(a)
    return out


def pull_side(cfg, parser, side_word, fetch):
    """All ads of one side, up to MAX_PAGES pages. fetch(kwargs) -> parsed JSON. Raises on a failed or malformed pull."""
    ads = []
    pages = 1 if parser.PAGE_ROWS is None else MAX_PAGES
    for page in range(1, pages + 1):
        got = parser.parse(fetch(parser.request(cfg, side_word, page)), side_word)
        ads += got
        if parser.PAGE_ROWS is None or len(got) < parser.PAGE_ROWS:
            break
    return ads


def build(ts, cfg, pulled, official):
    """Pure. pulled = {"buy": ads or Exception, "sell": ads or Exception}. Returns (ad_rows, seller_rows, basis_row)."""
    board, ccy = cfg["board"], cfg["ccy"]
    ad_rows, seller_rows, meds, n_use, errs = [], [], {}, 0, []
    for side in ("buy", "sell"):
        got = pulled[side]
        if isinstance(got, Exception):
            msg = ("%s:%s" % (type(got).__name__, got))[:120]
            ad_rows.append([ts, board, ccy, side, "", "", "", "", "", False, msg])
            errs.append("%s %s" % (side, msg))
            continue
        for i, a in enumerate(got, 1):
            ad_rows.append([ts, board, ccy, side, i, a["price"], a["available"], a["min_order"], a["max_order"], True, ""])
            seller_rows.append([ts, ts, board, ccy, side, i, sellers.seller_id(board, a["seller"]), a["price"], a["completion_rate"],
                                a["order_count"], a["merchant"], True, ""])
        if not got:
            ad_rows.append([ts, board, ccy, side, "", "", "", "", "", True, "no ads"])
        use = usable(got)
        n_use += len(use)
        if len(use) < cfg["min_ads"]:
            errs.append("%s: %d usable ads at ~USD 500, need %d (%d on the board)" % (side, len(use), cfg["min_ads"], len(got)))
            continue
        med = statistics.median(a["price"] for a in use)
        if official and abs(med / official - 1) > BAND:
            errs.append("guard: %s median %.4g is more than 30%% from the official rate %.4g" % (side, med, official))
            continue
        meds[side] = round(med, 6)
    ok = len(meds) == 2
    row = {"ts_utc": ts, "board": board, "ccy": ccy, "buy_median": meds.get("buy", ""), "sell_median": meds.get("sell", ""),
           "n_ads": n_use, "source_ok": ok, "error": "; ".join(errs)[:200]}
    return ad_rows, seller_rows, row


def default_fetch(kw):
    import requests
    r = requests.request(timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def collect_config(cfg, ts, fetch=default_fetch, official=None, pace=PAUSE):
    parser = boards.get(cfg["parser"])
    pulled = {}
    for i, side in enumerate(("buy", "sell")):
        if i and pace:
            time.sleep(pace)
        try:
            pulled[side] = pull_side(cfg, parser, cfg["sides"][side], fetch)
        except Exception as e:                       # a failed pull is a row, never a crash
            pulled[side] = e
    return build(ts, cfg, pulled, official if official is not None else official_rate(cfg["ccy"]))


def write_basis(rows, path=BASIS):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BASIS_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


def registry_problems(cfgs, registry_path=os.path.join(HERE, "data", "source_registry.json")):
    """A board with no row in the source registry has no quarantine status, so its config is refused."""
    with open(registry_path) as f:
        reg = json.load(f)["sources"]
    out = []
    for c in cfgs:
        name = boards.get(c["parser"]).REGISTRY
        if name not in reg:
            out.append("%s has no row in data/source_registry.json (it enters in quarantine first)" % name)
    return sorted(set(out))


def run_config_test(name, fetch=default_fetch, attempts=3):
    """What tests/agent_board_<board>_<ccy>.py runs: one live pull parses, the prices are within 30% of the official rate, and the row
    lands in the tables. Writes to a temporary directory, never to data/."""
    import tempfile
    cfg = load(config_path(name))
    official = official_rate(cfg["ccy"])
    assert official, "no official rate for %s in data/fx_rates.csv" % cfg["ccy"]
    last = None
    for k in range(attempts):
        ads, sel, row = collect_config(cfg, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), fetch, official)
        pulled = [r for r in ads if r[9] is True and r[4] != ""]
        if pulled:
            break
        last = row["error"]
        time.sleep(5)
    assert pulled, "%s: nothing parsed from a live pull after %d tries: %s" % (name, attempts, last)
    prices = [r[5] for r in pulled]
    assert all(abs(p / official - 1) <= BAND for p in sorted(prices)[len(prices) // 4: -(len(prices) // 4) or None]), \
        "%s: middle half of the prices is not within 30%% of the official rate %s: %s" % (name, official, sorted(prices)[:5])
    with tempfile.TemporaryDirectory() as d:
        daily_csv.append(ADS, ADS_FIELDS, ads, data=d)
        write_basis([row], os.path.join(d, "p2p_basis_boards.csv"))
        assert daily_csv.data_rows(ADS, d) == len(ads) > 0
        got = list(csv.DictReader(open(os.path.join(d, "p2p_basis_boards.csv"))))
        assert len(got) == 1 and got[0]["board"] == cfg["board"] and got[0]["ccy"] == cfg["ccy"], got
    return row


def new_test(name):
    """The text of tests/agent_board_<name>.py for a config. It is the same five lines for every config."""
    return ('"""SEB-422: one live pull of %s parses, the prices are within 30%% of the official rate, and the row lands."""\n'
            "import os\nimport sys\n\n"
            "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
            "from collectors import template_board as tb  # noqa: E402\n\n"
            "row = tb.run_config_test(%r)\n"
            "assert row[\"board\"] and row[\"ccy\"], row\n"
            "print(\"%s: ok\", row)\n") % (name, name, name)


def selftest():
    import tempfile
    ts = "2026-10-31T10:00:00Z"
    ad = lambda p, lo=100.0, hi=900000.0: {"price": p, "available": 1000.0, "min_order": lo, "max_order": hi, "seller": "u%s" % p,
                                           "completion_rate": 0.9, "order_count": 10.0, "merchant": False}
    cfg = {"board": "testboard", "ccy": "NGN", "pair": "USDT", "parser": "binance", "min_ads": 3, "sides": {"buy": "BUY", "sell": "SELL"}}
    good = {"buy": [ad(1370), ad(1372), ad(1375), ad(1380)], "sell": [ad(1310), ad(1312), ad(1315), ad(5, 1e9, 2e9)]}
    ads, sel, row = build(ts, cfg, good, 1340.0)
    assert row["source_ok"] and row["buy_median"] == 1373.5 and row["sell_median"] == 1312 and row["n_ads"] == 7, row
    assert len(ads) == 8 and len(sel) == 8 and sel[0][2] == "testboard" and len(sel[0][6]) == 16 and "u1370" not in str(sel), (ads, sel)
    assert len(sel[0]) == len(sellers.HEADER) and len(ads[0]) == len(ADS_FIELDS)
    # too few usable ads, a failed side, a median far from the official rate: each is a row with the reason, never a number
    ads, sel, row = build(ts, cfg, {"buy": good["buy"][:2], "sell": good["sell"]}, 1340.0)
    assert not row["source_ok"] and row["buy_median"] == "" and "need 3" in row["error"], row
    ads, sel, row = build(ts, cfg, {"buy": ValueError("not an ad list"), "sell": good["sell"]}, 1340.0)
    assert not row["source_ok"] and "ValueError" in row["error"] and ads[0][9] is False, row
    ads, sel, row = build(ts, cfg, {"buy": [ad(100), ad(101), ad(102)], "sell": good["sell"]}, 1340.0)
    assert not row["source_ok"] and "guard" in row["error"] and row["buy_median"] == "", row
    # the paging: a board of 25 ads on 20-row pages is two requests; a whole-book board is one
    class P:
        PAGE_ROWS = 20
        request = staticmethod(lambda cfg, side, page: {"page": page})
        parse = staticmethod(lambda payload, side: [ad(1.0)] * payload["n"])
    calls = []
    n = pull_side(cfg, P, "BUY", lambda kw: calls.append(kw) or {"n": 20 if kw["page"] == 1 else 5})
    assert len(n) == 25 and len(calls) == 2
    P.PAGE_ROWS = None
    calls.clear()
    assert len(pull_side(cfg, P, "BUY", lambda kw: calls.append(kw) or {"n": 7})) == 7 and len(calls) == 1
    # the five parsers on payloads shaped like the live answers
    b = boards.get("binance").parse({"code": "000000", "data": [{"adv": {"price": "1370", "tradableQuantity": "50", "minSingleTransAmount": "1000",
                                    "maxSingleTransAmount": "50000"}, "advertiser": {"userNo": "x", "monthFinishRate": 0.99, "userType": "merchant"}}]}, "BUY")
    assert b[0]["price"] == 1370.0 and b[0]["merchant"] and b[0]["seller"] == "x"
    o = boards.get("okx").parse({"code": 0, "data": {"sell": [{"price": "1371", "availableAmount": "10", "quoteMinAmountPerOrder": "100",
                                 "quoteMaxAmountPerOrder": "9000", "merchantId": "m", "creatorType": "certified"}], "buy": []}}, "sell")
    assert o[0]["price"] == 1371.0 and o[0]["merchant"] and boards.get("okx").parse({"code": 0, "data": {"sell": [], "buy": []}}, "buy") == []
    k = boards.get("kucoin").parse({"success": True, "items": [{"fiatToCryptoPrice": "0.5", "limitMinQuote": "1", "limitMaxQuote": "9"}, {"fiatToCryptoPrice": "0"}]}, "SELL")
    assert len(k) == 1 and k[0]["price"] == 2.0
    g = boards.get("bitget").parse({"code": "00000", "data": {"dataList": [{"price": "1315", "amount": "14144.74", "minAmount": "1000",
                                    "maxAmount": "65750", "encryptUserId": "e", "thirtyCompletionRate": "0.98", "certifiedMerchant": 1}]}}, "2")
    assert g[0]["price"] == 1315.0 and g[0]["completion_rate"] == 0.98 and g[0]["seller"] == "e"
    h = boards.get("htx").parse({"code": 200, "data": [{"price": "26449.00", "tradeCount": "1000.0", "minTradeLimit": "1000000.00",
                                 "maxTradeLimit": "26199000.00", "uid": 5, "orderCompleteRate": "97", "tradeMonthTimes": 176, "merchantLevel": 0}]}, "sell")
    assert h[0]["price"] == 26449.0 and h[0]["min_order"] == 1000000.0 and not h[0]["merchant"]
    for name, bad in (("binance", {"code": "1"}), ("okx", {"code": 1}), ("kucoin", {}), ("bitget", {"code": "1"}), ("htx", {"code": 500})):
        try:
            boards.get(name).parse(bad, "x")
            raise AssertionError(name + " accepted a bad answer")
        except ValueError:
            pass
    for blocked in boards.BLOCKED:
        try:
            boards.get(blocked)
            raise AssertionError("a blocked board has no parser")
        except SystemExit:
            pass
    # the written tables
    with tempfile.TemporaryDirectory() as d:
        ads, sel, row = build(ts, cfg, good, 1340.0)
        daily_csv.append(ADS, ADS_FIELDS, ads, data=d)
        write_basis([row], os.path.join(d, "b.csv"))
        write_basis([row], os.path.join(d, "b.csv"))
        assert open(os.path.join(d, "b.csv")).read().splitlines()[0] == ",".join(BASIS_FIELDS) and open(os.path.join(d, "b.csv")).read().count("\n") == 3
        assert daily_csv.data_rows(ADS, d) == 8
    t = new_test("bitget_NGN")
    compile(t, "t", "exec")
    assert "run_config_test('bitget_NGN')" in t
    print("template_board self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--self-test" in sys.argv else (print(__doc__) or 2))
