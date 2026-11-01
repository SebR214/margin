#!/usr/bin/env python3
"""The history a money-changer tracker publishes, stored as "reported, not observed" (SEB-422, step 3). No model, no key.

    python3 tools/pull_cash_history.py            # Argentina's blue dollar from argentinadatos.com, since 2011
    python3 tools/pull_cash_history.py --self-test

Writes data/history/ar_blue_argentinadatos.csv: date, ccy, buy, sell, label, source. Every row carries the label and the source and no
field is empty (rows without a number are left out, never filled). It never feeds the index, a price or the unbroken-hours count
(tools/check_history_isolation.py). A file that already exists is rewritten only with the same rows plus newer ones; it never loses one.
"""
import csv
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://api.argentinadatos.com/v1/cotizaciones/dolares"
OUT = os.path.join(ROOT, "data", "history", "ar_blue_argentinadatos.csv")
FIELDS = ["date", "ccy", "buy", "sell", "label", "source"]
LABEL = "reported, not observed"
SOURCE = "api.argentinadatos.com/v1/cotizaciones/dolares, casa=blue (what the tracker reports for the informal market)"


def rows_from(doc):
    out = {}
    for d in doc:
        if d.get("casa") != "blue" or not d.get("fecha"):
            continue
        b, s = d.get("compra"), d.get("venta")
        if not b or not s or b <= 0 or s <= 0:
            continue
        out[d["fecha"]] = [d["fecha"], "ARS", b, s, LABEL, SOURCE]
    return [out[k] for k in sorted(out)]


def merge(old, new):
    """Old rows are kept as they are; new rows are added by date. A date the tracker now reports differently keeps the stored row."""
    have = {r[0] for r in old}
    return old + [r for r in new if r[0] not in have]


def main(argv):
    if "--self-test" in argv:
        doc = [{"casa": "blue", "compra": 4, "venta": 4.1, "fecha": "2011-01-03"}, {"casa": "oficial", "compra": 3, "venta": 3, "fecha": "2011-01-03"},
               {"casa": "blue", "compra": None, "venta": 4, "fecha": "2011-01-04"}, {"casa": "blue", "compra": 5, "venta": 5.2, "fecha": "2011-01-05"}]
        r = rows_from(doc)
        assert [x[0] for x in r] == ["2011-01-03", "2011-01-05"] and all(x[4] == LABEL and x[5] for x in r), r
        assert merge([r[0][:2] + ["9", "9"] + r[0][4:]], r)[0][2] == "9" and len(merge([r[0]], r)) == 2
        print("pull_cash_history self-test: ok")
        return 0
    req = urllib.request.Request(URL, headers={"User-Agent": "margin.wiki/1.0 (+https://margin.wiki)"})
    with urllib.request.urlopen(req, timeout=60) as f:
        new = rows_from(json.load(f))
    if not new:
        print("pull_cash_history: the tracker returned no blue rows", file=sys.stderr)
        return 1
    old = []
    if os.path.exists(OUT):
        with open(OUT, newline="") as f:
            old = list(csv.reader(f))[1:]
    rows = merge(old, new)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        w.writerows(rows)
    print("pull_cash_history: %d rows, %s to %s" % (len(rows), rows[0][0], rows[-1][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
