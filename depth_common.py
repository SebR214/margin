"""The depth record (SEB-302, steps 1 and 2): how much money can move at a price, from today.

Shared by collector_depth.py (the order books) and, once the hook is merged, collector_p2p_okx.py (OKX ads, from the call it
already makes). Pure functions plus the one CSV, data/depth.csv. It feeds nothing published: no page, no copy, no finding, no price.

    ts_utc,source,ccy,kind,param,avg_price,index_pct,usd_available,n_ads,status,source_ok,reason

kind  book_fill        walk the ask side to buy `param` US dollars (param = 500, 5000, 25000, 100000)
                       avg_price = what was paid per dollar, local money; index_pct = that against the official rate, same row;
                       usd_available = dollars on the ask side in total; status filled | not_fillable
      book_within      dollars on offer within `param` percent (0.5, 1, 2) of the best ask; usd_available = that sum
      p2p_accepts      person-to-person ads: how many buy ads accept a ticket of `param` US dollars (500, 2000, 10000), n_ads = that
                       count, avg_price = the median price among them (empty when fewer than 10 accept), status ok | thin
status failed          the pull failed (source_ok false), reason says why. A gap stays a gap: nothing is filled in.
A book that runs out before a size is written as not_fillable with how much was available. Nothing is extrapolated.
"""
import csv
import datetime as dt
import os
import statistics
import sys

HEADER = ["ts_utc", "source", "ccy", "kind", "param", "avg_price", "index_pct", "usd_available", "n_ads", "status", "source_ok", "reason"]
FILL_SIZES = (500, 5000, 25000, 100000)
BANDS = (0.5, 1, 2)
P2P_SIZES = (500, 2000, 10000)
MIN_ADS = 10
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
import daily_csv  # noqa: E402
NAME = "depth"      # one file a day, data/depth/<day>.csv, or margin-data/depth/<day>.csv (SEB-422); the closed data/depth.csv is read first
PATH = None         # the default: the table above. A test passes a plain file path.


def fnum(v):
    try:
        x = float(v)
        return x if x == x and x > 0 else None
    except (TypeError, ValueError):
        return None


def levels(rows):
    """[(price, qty)] from any list of pairs, dicts or a price->qty map, positive numbers only, sorted by price ascending."""
    out = []
    if isinstance(rows, dict):
        rows = list(rows.items())
    for r in rows or []:
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            p, q = fnum(r[0]), fnum(r[1])
        else:
            continue
        if p and q:
            out.append((p, q))
    return sorted(out)


def walk_fill(asks, size):
    """Buy `size` dollars walking up the ask side. Returns (avg_price, status, total_available): avg_price None when not fillable."""
    total = sum(q for _, q in asks)
    if total < size:
        return None, "not_fillable", total
    need, paid = size, 0.0
    for p, q in asks:
        take = min(q, need)
        paid += take * p
        need -= take
        if need <= 1e-9:
            break
    return paid / size, "filled", total


def within(asks, pct):
    """Dollars on offer within `pct` percent of the best ask."""
    if not asks:
        return 0.0
    cap = asks[0][0] * (1 + pct / 100.0)
    return sum(q for p, q in asks if p <= cap)


def pct_vs(price, fx):
    return round((price / fx - 1) * 100, 4) if price and fx else ""


def book_rows(ts, source, ccy, asks, fx):
    """The depth rows of one order book: four fills and three bands."""
    rows = []
    for size in FILL_SIZES:
        avg, status, total = walk_fill(asks, size)
        rows.append([ts, source, ccy, "book_fill", size, round(avg, 8) if avg else "", pct_vs(avg, fx), round(total, 2), "", status, "true",
                     "" if avg else "the book holds %.2f dollars on the ask side, less than %d" % (total, size)])
    for band in BANDS:
        rows.append([ts, source, ccy, "book_within", band, "", "", round(within(asks, band), 2), "", "ok", "true", ""])
    return rows


def failed_row(ts, source, ccy, why):
    return [ts, source, ccy, "failed", "", "", "", "", "", "failed", "false", str(why)[:200].replace("\n", " ")]


def bound(v):
    return fnum(v)


def p2p_rows(ts, source, ccy, ads, fx):
    """Person-to-person ads, from the call that is already made. `ads` are dicts with price, quoteMinAmountPerOrder and
    quoteMaxAmountPerOrder (the order limits in local money; an ad missing either limit is not counted, as in the OKX price). For each ticket size the count of ads that
    accept it and the median of their prices; under MIN_ADS accepting ads the price is left empty."""
    rows = []
    for usd in P2P_SIZES:
        local = usd * fx
        prices = []
        for ad in ads:
            p = fnum(ad.get("price"))
            lo, hi = bound(ad.get("quoteMinAmountPerOrder")), bound(ad.get("quoteMaxAmountPerOrder"))
            if p and lo is not None and hi is not None and lo <= local <= hi:     # an ad without both limits is not counted, as in the OKX price
                prices.append(p)
        n = len(prices)
        thin = n < MIN_ADS
        med = statistics.median(prices) if prices and not thin else None
        rows.append([ts, source, ccy, "p2p_accepts", usd, round(med, 8) if med else "", pct_vs(med, fx), "", n, "thin" if thin else "ok", "true",
                     "fewer than %d ads accept this size" % MIN_ADS if thin else ""])
    return rows


def captured_this_hour(path=PATH, now=None, okx=False):
    """True if this clock hour already has rows: the order books' (okx=False) or the OKX ads' (okx=True), written by two different
    collectors, each once an hour. Reads only the end of the file."""
    now = now or dt.datetime.now(dt.timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    if path is None:
        tail = daily_csv.tail(NAME, 400_000)[1:]
    else:
        if not os.path.exists(path):
            return False
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 400_000))
            tail = f.read().decode("utf-8", "replace").split("\n")[1:]
    for r in csv.reader(tail):
        if len(r) < 2 or not r[0]:
            continue
        try:
            when = dt.datetime.fromisoformat(r[0])
        except ValueError:
            continue
        if when >= start and (r[1] == "okx_p2p") == okx:
            return True
    return False


def append(rows, path=PATH):
    if path is None:
        daily_csv.append(NAME, HEADER, rows)
        return
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerows(rows)
