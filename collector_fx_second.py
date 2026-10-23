#!/usr/bin/env python3
"""A second official rate beside er-api, from Frankfurter's v2 feed (BACKLOG item 10). Collected, compared, NOT published as the rate.

collector_fx.py writes the rate every index figure is divided by, from open.er-api.com. A source cannot check itself, and the
official rate had no second source for most currencies (the older Frankfurter v1 feed is the ECB's 29 currencies, 10 of ours).
Frankfurter's v2 feed (api.frankfurter.dev/v2/rates?base=USD) blends central banks and covers every currency we price. This
reads it once a run and stores each currency's rate beside the er-api rate of the same hour:

    data/fx_second.csv
    ts_utc,ccy,rate_per_usd,source,source_date,er_api_rate,gap_pct,source_ok,error

One row per currency we price per run. source_date is the day the source stamps on that rate, as it gave it (some currencies are a
day behind); ts_utc is our clock, whole seconds, the same for every row of the run. er_api_rate is the newest open.er-api row for
the currency in data/fx_rates.csv (blank when the denominator came from another source that hour: a rate is only compared with
er-api's own). gap_pct is (this rate / er-api rate - 1) * 100. A currency the feed does not carry is a row with source_ok false and
"not in the feed". A rate more than five times or less than a fifth of er-api's is a broken read, not news: source_ok false. A failed
pull is a row per currency with source_ok false and the reason, never a gap and never a copy of the last hour. The run exits non-zero
if no currency was read.

Nothing reads this file except tools/emit_source_pairs.py, which compares the two rates hour by hour into data/source_pairs.json
("official"). The published rate, fx_rates.csv and every index figure are untouched, so index_version does not move. Under
quarantine by construction until Seb switches something to read it.

Usage:  python3 collector_fx_second.py             # one pass, appends to data/fx_second.csv
        python3 collector_fx_second.py --selftest   # parser and gap rules on fixtures, no network, writes nothing
"""
import csv
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "fx_second.csv")
FX = os.path.join(HERE, "data", "fx_rates.csv")
URL = "https://api.frankfurter.dev/v2/rates?base=USD"
SOURCE = "frankfurter-v2"
FIELDS = ["ts_utc", "ccy", "rate_per_usd", "source", "source_date", "er_api_rate", "gap_pct", "source_ok", "error"]
TIMEOUT = 30
UA = {"User-Agent": "margin.wiki/1.0 (+https://margin.wiki)"}
BROKEN_RATIO = 5.0
TAIL_BYTES = 262144          # the newest rows of fx_rates.csv are at the end; an hour of rows is about 6 KB


def num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_rates(payload):
    """The v2 response, a list of {date, base, quote, rate}, as {quote: (rate, date)}. A malformed answer raises ValueError."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("not a list of rates")
    out = {}
    for x in payload:
        if not isinstance(x, dict) or x.get("base") != "USD":
            continue
        r, q = num(x.get("rate")), x.get("quote")
        if r and q and x.get("date"):
            out[q] = (r, str(x["date"]))
    if not out:
        raise ValueError("no usable rate in the answer")
    return out


def latest_erapi(path=FX):
    """{ccy: newest open.er-api rate} from the tail of data/fx_rates.csv. Rows from another source are not er-api's rate."""
    if not os.path.exists(path):
        return {}, []
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    with open(path, newline="") as f:
        header = next(csv.reader(f))
    rows = [dict(zip(header, ln.split(","))) for ln in lines if ln.count(",") >= len(header) - 1 and not ln.startswith("ts_utc")]
    newest = max((r["ts_utc"] for r in rows), default=None)
    ccys = sorted({r["ccy"] for r in rows if r["ts_utc"] == newest})        # the currencies priced in the newest run
    er = {}
    for r in rows:
        if r.get("source") == "open.er-api" and num(r.get("fx_mid_per_usd")):
            er[r["ccy"]] = float(r["fx_mid_per_usd"])                          # later rows overwrite earlier ones
    return er, ccys


def build_rows(ts, ccys, er, rates, error=None):
    """One row per currency. Pure. rates is {quote: (rate, date)} or None when the pull failed (error says why)."""
    out = []
    for c in ccys:
        e = er.get(c)
        row = {"ts_utc": ts, "ccy": c, "rate_per_usd": "", "source": SOURCE, "source_date": "", "er_api_rate": e if e else "",
               "gap_pct": "", "source_ok": False, "error": ""}
        if rates is None:
            row["error"] = (error or "pull failed")[:120]
        elif c not in rates:
            row["error"] = "not in the feed"
        else:
            r, d = rates[c]
            row["rate_per_usd"], row["source_date"] = r, d
            if e:
                row["gap_pct"] = round((r / e - 1) * 100, 4)
                if r > e * BROKEN_RATIO or r < e / BROKEN_RATIO:
                    row["error"] = "more than 5x apart from er-api: a broken read"
                else:
                    row["source_ok"] = True
            else:
                row["source_ok"] = True                                          # a rate with nothing to compare it with is still a reading
        out.append(row)
    return out


def write(rows, path=OUT):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


def collect():
    import requests                                    # imported here so the offline self-test runs without it
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    er, ccys = latest_erapi()
    if not ccys:
        sys.exit("collector_fx_second: no currencies in data/fx_rates.csv")
    rates, err = None, None
    try:
        r = requests.get(URL, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        rates = parse_rates(r.json())
    except Exception as e:                                # a failed pull is rows saying so, then a non-zero exit
        err = "%s:%s" % (type(e).__name__, e)
    rows = build_rows(ts, ccys, er, rates, err)
    write(rows)                                          # persistence before display
    ok = sum(1 for r in rows if r["source_ok"])
    print("collector_fx_second: %d of %d currencies read%s" % (ok, len(rows), "" if rates else " (pull failed: %s)" % err))
    for r in rows:
        if not r["source_ok"]:
            print("  %s: %s" % (r["ccy"], r["error"]))
    return 0 if ok else 1


def selftest():
    payload = [{"date": "2026-10-23", "base": "USD", "quote": "AED", "rate": 3.6725},
               {"date": "2026-10-22", "base": "USD", "quote": "AWG", "rate": 1.79},
               {"date": "2026-10-23", "base": "USD", "quote": "SDG", "rate": 600.0},
               {"date": "2026-10-23", "base": "USD", "quote": "BAD", "rate": 0},
               {"date": "2026-10-23", "base": "EUR", "quote": "AED", "rate": 4.0}]
    rates = parse_rates(payload)
    assert rates == {"AED": (3.6725, "2026-10-23"), "AWG": (1.79, "2026-10-22"), "SDG": (600.0, "2026-10-23")}, rates
    for bad in ([], {}, [{"base": "USD", "quote": "X", "rate": -1, "date": "d"}], "x"):
        try:
            parse_rates(bad)
        except ValueError:
            continue
        raise AssertionError("malformed answer accepted: %r" % (bad,))
    er = {"AED": 3.6725, "SDG": 449.2, "ZZZ": 10.0}
    rows = {r["ccy"]: r for r in build_rows("t", ["AED", "AWG", "SDG", "ZZZ", "QQQ"], er, rates)}
    assert rows["AED"]["source_ok"] and rows["AED"]["gap_pct"] == 0.0 and rows["AED"]["source_date"] == "2026-10-23", rows["AED"]
    assert rows["AWG"]["source_ok"] and rows["AWG"]["er_api_rate"] == "" and rows["AWG"]["gap_pct"] == "", "nothing to compare with is still a reading"
    assert rows["SDG"]["source_ok"] and abs(rows["SDG"]["gap_pct"] - 33.5) < 0.1, rows["SDG"]
    assert not rows["ZZZ"]["source_ok"] and rows["ZZZ"]["error"] == "not in the feed", rows["ZZZ"]
    broke = build_rows("t", ["SDG"], {"SDG": 100.0}, rates)[0]
    assert not broke["source_ok"] and "5x" in broke["error"], broke
    failed = build_rows("t", ["AED", "SDG"], er, None, "ConnectionError:x")
    assert all(not r["source_ok"] and r["rate_per_usd"] == "" and r["error"].startswith("Conn") for r in failed), failed
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "fx_rates.csv")
        with open(p, "w") as f:
            f.write("ts_utc,ccy,fx_mid_per_usd,source,managed_flag,parallel_rate_per_usd,parallel_source\n")
            f.write("2026-10-23T05:00:00Z,AED,3.6,open.er-api,False,,\n2026-10-23T05:00:00Z,SDG,449.2,open.er-api,True,,\n")
            f.write("2026-10-23T06:00:00Z,AED,3.6725,open.er-api,False,,\n2026-10-23T06:00:00Z,SDG,500.0,frankfurter,True,,\n")
        e, cc = latest_erapi(p)
        assert cc == ["AED", "SDG"] and e == {"AED": 3.6725, "SDG": 449.2}, (e, cc)
        o = os.path.join(tmp, "out.csv")
        write(rows.values(), o)
        write([rows["AED"]], o)
        with open(o) as f:
            got = list(csv.reader(f))
        assert got[0] == FIELDS and len(got) == 1 + 5 + 1, got[:2]
    print("collector_fx_second self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else collect())
