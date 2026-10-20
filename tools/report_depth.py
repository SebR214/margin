#!/usr/bin/env python3
"""A one-day table from data/depth.csv, and the file's growth (SEB-302, depth record). Reads the file, writes nothing.

    python3 tools/report_depth.py                 # the last 24 hours of rows, as markdown
    python3 tools/report_depth.py --size          # bytes per row, rows per hour and a month's growth, from what is stored
    python3 tools/report_depth.py --self-test

Per country and source: the figure against the official rate at each size (median over the hours in the window), how many hours the book
filled that size, and the dollars on offer within 0.5%, 1% and 2% of the best ask; for the person-to-person ads, the figure and the number
of ads that accept each size. Nothing is estimated: an hour that did not fill a size is counted as not filled, and its price is left out.
"""
import collections
import csv
import datetime as dt
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "depth.csv")


def load(path=PATH):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def table(rows, since):
    rows = [r for r in rows if r["ts_utc"] >= since]
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["ccy"], r["source"])].append(r)
    out = ["| Country | Source | Size (US$) | Figure against the official rate | Hours filled | Dollars within 0.5% / 1% / 2% of the best ask |",
           "|---|---|---|---|---|---|"]
    for (ccy, src), rs in sorted(by.items()):
        fills = collections.defaultdict(list)
        within = collections.defaultdict(list)
        p2p = collections.defaultdict(list)
        for r in rs:
            if r["kind"] == "book_fill":
                fills[r["param"]].append(r)
            elif r["kind"] == "book_within" and r["usd_available"]:
                within[r["param"]].append(float(r["usd_available"]))
            elif r["kind"] == "p2p_accepts":
                p2p[r["param"]].append(r)
        wtxt = " / ".join("{:,.0f}".format(statistics.median(within[b])) if within.get(b) else "-" for b in ("0.5", "1", "2"))
        for size, g in sorted(fills.items(), key=lambda kv: float(kv[0])):
            ok = [float(x["index_pct"]) for x in g if x["status"] == "filled" and x["index_pct"] != ""]
            out.append("| %s | %s | %s | %s | %d of %d | %s |" % (ccy, src, "{:,.0f}".format(float(size)),
                       ("%+.2f%%" % statistics.median(ok)) if ok else "not filled", len(ok), len(g), wtxt if size == min(fills, key=float) else ""))
        for size, g in sorted(p2p.items(), key=lambda kv: float(kv[0])):
            ok = [float(x["index_pct"]) for x in g if x["index_pct"] != ""]
            n = [int(x["n_ads"]) for x in g if x["n_ads"] != ""]
            out.append("| %s | %s | %s | %s | %d of %d (median %s ads accept) | |" % (ccy, src, "{:,.0f}".format(float(size)),
                       ("%+.2f%%" % statistics.median(ok)) if ok else "fewer than 10 ads", len(ok), len(g), "%d" % statistics.median(n) if n else "-"))
    return "\n".join(out), len(rows)


def size_report(path=PATH):
    rows = load(path)
    hours = len({r["ts_utc"][:13] for r in rows})
    size = os.path.getsize(path)
    per_hour = size / max(hours, 1)
    return {"bytes": size, "rows": len(rows), "hours": hours, "bytes_per_row": round(size / max(len(rows), 1), 1),
            "mb_per_month": round(per_hour * 24 * 30 / 1e6, 2)}


def self_test():
    import tempfile
    head = "ts_utc,source,ccy,kind,param,avg_price,index_pct,usd_available,n_ads,status,source_ok,reason\n"
    body = ("2026-10-20T09:00:00+00:00,V,XYZ,book_fill,500,1.01,1.0,1000,,filled,true,\n"
            "2026-10-20T09:00:00+00:00,V,XYZ,book_fill,5000,,,1000,,not_fillable,true,x\n"
            "2026-10-20T09:00:00+00:00,V,XYZ,book_within,0.5,,,400,,ok,true,\n"
            "2026-10-20T09:00:00+00:00,V,XYZ,book_within,1,,,600,,ok,true,\n"
            "2026-10-20T09:00:00+00:00,V,XYZ,book_within,2,,,800,,ok,true,\n"
            "2026-10-20T09:00:00+00:00,okx_p2p,XYZ,p2p_accepts,500,101,1.5,,12,ok,true,\n"
            "2026-10-20T09:00:00+00:00,okx_p2p,XYZ,p2p_accepts,10000,,,,3,thin,true,x\n"
            "2026-10-19T08:00:00+00:00,V,XYZ,book_fill,500,1.5,9.0,1000,,filled,true,\n")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "depth.csv")
        open(p, "w").write(head + body)
        t, n = table(load(p), "2026-10-19T12:00:00")
        assert n == 7 and "+1.00%" in t and "not filled" in t and "400 / 600 / 800" in t and "fewer than 10 ads" in t, t
        s = size_report(p)
        assert s["rows"] == 8 and s["hours"] == 2 and s["mb_per_month"] > 0
    print("report_depth self-test: ok")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--size" in argv:
        s = size_report()
        print("data/depth.csv: %(rows)d rows over %(hours)d hours, %(bytes)d bytes (%(bytes_per_row)s per row); a month at this rate: %(mb_per_month)s MB" % s)
        return 0
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
    t, n = table(load(), since)
    print("Last 24 hours of data/depth.csv: %d rows.\n" % n)
    print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
