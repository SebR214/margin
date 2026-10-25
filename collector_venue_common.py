"""Shared pure parts of the first-venue collectors (SEB-301, BACKLOG 17). Not a collector: nothing runs from here.

Used by collector_zar_valr.py, collector_zar_luno.py and collector_p2p_kucoin.py, each of which writes its own
new CSV with the one header below. A price is stored as the venue gave it; a failed pull is a row with source_ok false and the reason.

    ts_utc,venue,ccy,kind,n_board,n_ads,ask_best,ask_ref,bid_best,bid_ref,source_ok,error

kind is "book" (an order book) or "board" (a person-to-person ad board). ask_ref is what a USD 500 purchase of the stablecoin pays
per dollar: for a book the volume-weighted price of the first 500 USDT of asks; for a board the median price of the ads whose order
limits take a USD 500 order (n_ads counts those, n_board counts every ad the board returned). bid_ref is the same walk down the bids
of a book; a board has no bid side here and leaves it blank. Nothing reads these files: a new source starts in quarantine
(data/source_registry.json) and feeds no price until Seb switches it.
"""
import csv
import datetime as dt
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ["ts_utc", "venue", "ccy", "kind", "n_board", "n_ads", "ask_best", "ask_ref", "bid_best", "bid_ref", "source_ok", "error"]
UA = {"User-Agent": "margin.wiki/1.0 (+https://margin.wiki)"}
TIMEOUT = 25
NOTIONAL_USDT = 500.0


def now_ts():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def walk(levels, qty=NOTIONAL_USDT):
    """Volume-weighted price of the first qty USDT of levels [(price, size)], best first. None if the book is too thin."""
    need, paid = qty, 0.0
    for p, s in levels:
        take = min(need, s)
        paid += take * p
        need -= take
        if need <= 1e-9:
            return paid / qty
    return None


def book_row(ts, venue, ccy, asks, bids, error=None):
    """One row from an order book. asks and bids are [(price, size)]. Pure. asks=None means the pull failed (error says why)."""
    row = {"ts_utc": ts, "venue": venue, "ccy": ccy, "kind": "book", "n_board": "", "n_ads": "", "ask_best": "", "ask_ref": "",
           "bid_best": "", "bid_ref": "", "source_ok": False, "error": ""}
    if asks is None or bids is None:
        row["error"] = (error or "pull failed")[:120]
        return row
    asks = sorted((p, s) for p, s in asks if p and s)
    bids = sorted(((p, s) for p, s in bids if p and s), reverse=True)
    row["n_board"] = row["n_ads"] = len(asks) + len(bids)
    if not asks or not bids:
        row["error"] = "empty side of the book"
        return row
    row["ask_best"], row["bid_best"] = asks[0][0], bids[0][0]
    if bids[0][0] >= asks[0][0]:
        row["error"] = "guard: crossed book"
        return row
    a, b = walk(asks), walk(bids)
    row["ask_ref"], row["bid_ref"] = ("" if a is None else round(a, 6)), ("" if b is None else round(b, 6))
    if a is None or b is None:
        row["error"] = "book too thin for 500 USDT"
        return row
    row["source_ok"] = True
    return row


def board_row(ts, venue, ccy, ads, error=None):
    """One row from an ad board. ads is [(price, min_fiat, max_fiat)] for ads that SELL USDT; None means the pull failed. Pure."""
    row = {"ts_utc": ts, "venue": venue, "ccy": ccy, "kind": "board", "n_board": "", "n_ads": "", "ask_best": "", "ask_ref": "",
           "bid_best": "", "bid_ref": "", "source_ok": False, "error": ""}
    if ads is None:
        row["error"] = (error or "pull failed")[:120]
        return row
    ads = [a for a in ads if a[0]]
    row["n_board"] = len(ads)
    usable = sorted(p for p, lo, hi in ads if (lo is None or lo <= NOTIONAL_USDT * p) and (hi is None or hi >= NOTIONAL_USDT * p))
    row["n_ads"] = len(usable)
    if ads:
        row["ask_best"] = min(a[0] for a in ads)
    if not usable:
        row["error"] = "no ads at ~USD 500 (%d on the board)" % len(ads)
        return row
    row["ask_ref"] = round(statistics.median(usable), 6)
    row["source_ok"] = True
    return row


def write(rows, path):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


def finish(name, rows, path):
    """Persist, then print, then the exit code: non-zero when nothing was read."""
    write(rows, path)
    ok = sum(1 for r in rows if r["source_ok"])
    print("%s: %d of %d read" % (name, ok, len(rows)))
    for r in rows:
        if not r["source_ok"]:
            print("  %s: %s" % (r["ccy"], r["error"]))
    return 0 if ok else 1


def selftest_common():
    asks = [(16.7, 1000), (16.6, 300), (16.65, 400)]
    bids = [(16.5, 200), (16.55, 500), (16.4, 5000)]
    r = book_row("t", "V", "ZAR", asks, bids)
    assert r["source_ok"] and r["ask_best"] == 16.6 and r["bid_best"] == 16.55, r
    assert abs(r["ask_ref"] - (300 * 16.6 + 200 * 16.65) / 500) < 1e-5, r
    assert not book_row("t", "V", "ZAR", [(16.0, 9999)], [(16.1, 9999)])["source_ok"], "crossed book accepted"
    assert "thin" in book_row("t", "V", "ZAR", [(16.6, 10)], [(16.5, 10)])["error"]
    assert not book_row("t", "V", "ZAR", [], [(16.5, 10)])["source_ok"]
    f = book_row("t", "V", "ZAR", None, None, "HTTPError:500")
    assert not f["source_ok"] and f["ask_ref"] == "" and f["error"] == "HTTPError:500", f
    ads = [(12.0, 100.0, 50000.0), (12.5, 100.0, 50000.0), (13.0, 100.0, 50000.0), (11.0, 100000.0, 200000.0), (11.5, 10.0, 100.0)]
    b = board_row("t", "B", "GHS", ads)
    assert b["source_ok"] and b["n_board"] == 5 and b["n_ads"] == 3 and b["ask_ref"] == 12.5 and b["ask_best"] == 11.0, b
    e = board_row("t", "B", "GHS", [(11.0, 100000.0, 200000.0)])
    assert not e["source_ok"] and e["error"].startswith("no ads at"), e
    assert board_row("t", "B", "GHS", [])["error"].startswith("no ads at")
    assert not board_row("t", "B", "GHS", None, "boom")["source_ok"]
    assert num("0") is None and num("x") is None and num("1.5") == 1.5
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "o.csv")
        write([r, b], p)
        write([r], p)
        with open(p) as fh:
            got = list(csv.reader(fh))
        assert got[0] == FIELDS and len(got) == 4 and all(len(x) == len(FIELDS) for x in got), got
