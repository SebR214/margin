#!/usr/bin/env python3
"""Index v1.5 (crossed boards), before and after, on the stored rows (SEB-302).

    python3 tools/v15_before_after.py [--days 7]

Runs tools/emit_countries.py's own hourly rule (`_hour_value`) over the last N days of stored rows twice: with the v1.4 rule
(emit_countries.V15 = False) and with v1.5, and prints, for every country whose count of priced hours changes: hours priced
before and after, the median published figure before and after, and how far the new hours' median sits from that country's own
published history (data/index_hourly.csv). It reads files and writes nothing. A figure here is the hourly value before the v1.4
sudden-flip hold, so it can differ from data/index_hourly.csv in an hour that hold judged.
"""
import csv
import datetime as dt
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emit_countries as ec  # noqa: E402


def run(days):
    book_hours, p2p_hours, okx_hours, okx_series = ec.load_hours()
    sides = ec.buy_side_counts()
    book = ec.fx_book()
    newest = max(h for hs in p2p_hours.values() for h in hs)
    hours = [newest - dt.timedelta(hours=i) for i in range(days * 24)]
    out = {}
    for ccy in sorted(set(book_hours) | set(p2p_hours)):
        bh, ph = book_hours.get(ccy) or {}, p2p_hours.get(ccy) or {}
        res = {}
        for v15 in (False, True):
            ec.V15 = v15
            vals = {}
            for h in hours:
                v = ec._hour_value(ccy, h, bh, ph, sides, book, okx_hours, okx_series)
                if v is not None:
                    vals[h] = v
            res[v15] = vals
        out[ccy] = res
    ec.V15 = True
    return newest, hours, out


def published(path, hours):
    want = {h.strftime("%Y-%m-%dT%H") for h in hours}
    by = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["hour_utc"][:13] in want and r["index_pct"] != "":
                by.setdefault(r["ccy"], []).append(float(r["index_pct"]))
    return by


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    newest, hours, res = run(days)
    pub = published(os.path.join(ec.DATA, "index_hourly.csv"), hours)
    print("Last %d days of stored rows, to %s UTC (%d hours). Hours priced and median figure, v1.4 rule then v1.5 rule.\n" % (days, newest.strftime("%d %b %H:00"), len(hours)))
    print("| Country | Hours priced before | after | Median before | after | New hours' median against the published history |")
    print("|---|---|---|---|---|---|")
    moved = []
    for ccy, r in res.items():
        b, a = r[False], r[True]
        if len(a) == len(b):
            continue
        med = lambda d: ("%+.2f%%" % statistics.median(d.values())) if d else "none"
        new_hours = [v for h, v in a.items() if h not in b]
        hist = pub.get(ccy) or []
        if new_hours and hist:
            diff = statistics.median(new_hours) - statistics.median(hist)
            note = "%+.2f points (history median %+.2f%%, %d published hours)" % (diff, statistics.median(hist), len(hist))
            if abs(diff) > 1:
                moved.append((ccy, diff))
        else:
            note = "no published history in the window" if new_hours else ""
        print("| %s | %d | %d | %s | %s | %s |" % (ec.COUNTRY.get(ccy, ccy), len(b), len(a), med(b), med(a), note))
    for ccy, d in moved:
        print("\nMoves by more than 1 point against its own published history: %s (%+.2f points)" % (ec.COUNTRY.get(ccy, ccy), d))
    lost = [c for c, r in res.items() if set(r[False]) - set(r[True])]
    print("\nHours priced under v1.4 and not under v1.5 (should be none): %s" % (", ".join(lost) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
