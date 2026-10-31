#!/usr/bin/env python3
"""Why do Binance P2P and OKX P2P disagree in the flagged markets? (BACKLOG 20a, SEB-301.)

Reads the pairs with flag true in data/source_pairs.json (the markets where two sources sit more than gap_pct apart for hours in a
row) and, for each, the newest 168 hours both venues have rows in: Binance from data/p2p_basis.csv, OKX from data/p2p_okx.csv (the
same columns, one row per run, only source_ok rows). Per hour and side (buy, sell) each venue's median price; the gap of a side is
|OKX / Binance - 1| in percent. Writes data/disagree_diagnosis.json, per market:

    gap_side            the side (buy or sell) whose median gap is larger
    median_gap_pct      the median gap of each side over the hours
    share_on_side       the share of hours the gap is larger on that side than on the other
    median_ads          the median ads per run, per venue (n_ads in the two files)
    median_min_order    the median minimum order per venue where the column exists (Binance, from data/p2p_ads.csv; OKX has none)
    label               chosen by code, in this order:
                          'not enough evidence'    fewer than MIN_HOURS hours both venues have rows
                          'one side thin'          fewer than 10 ads on either venue
                          'one side moves alone'   the gap is larger on the same side in over 80% of hours
                          'unexplained'

A diagnosis, not a correction: no price, index figure or source status changes. Usage:
    python3 tools/diagnose_disagree.py             # writes data/disagree_diagnosis.json
    python3 tools/diagnose_disagree.py --self-test
"""
import csv
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_csv  # noqa: E402
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "disagree_diagnosis.json")
WINDOW_HOURS = 168
MIN_HOURS = 8
THIN_ADS = 10
ALONE_SHARE = 0.8
A, B = "binance_p2p", "okx_p2p"


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def hourly(rows):
    """{hour: {"buy": price, "sell": price, "ads": median n_ads}} from one venue's rows of one market (medians over the hour's runs)."""
    per = {}
    for r in rows:
        h = r["ts_utc"][:13]
        per.setdefault(h, {"buy": [], "sell": [], "ads": []})
        for k, col in (("buy", "buy_median"), ("sell", "sell_median"), ("ads", "n_ads")):
            v = fnum(r.get(col))
            if v is not None:
                per[h][k].append(v)
    return {h: {k: st.median(v) for k, v in d.items() if v} for h, d in per.items()}


def diagnose(a_rows, b_rows, a_min_order=None, b_min_order=None):
    """One market's diagnosis from the two venues' rows (dicts with ts_utc, buy_median, sell_median, n_ads). Pure."""
    ha, hb = hourly(a_rows), hourly(b_rows)
    hours = sorted(h for h in ha if h in hb and all(s in ha[h] and s in hb[h] for s in ("buy", "sell")))[-WINDOW_HOURS:]
    out = {"hours": len(hours), "gap_side": None, "median_gap_pct": {"buy": None, "sell": None}, "share_on_side": None,
           "median_ads": {A: None, B: None}, "median_min_order": {A: a_min_order, B: b_min_order}, "label": "not enough evidence"}
    if len(hours) < MIN_HOURS:
        return out
    gap = {s: [abs(hb[h][s] / ha[h][s] - 1) * 100 for h in hours if ha[h][s] > 0] for s in ("buy", "sell")}
    out["median_gap_pct"] = {s: round(st.median(g), 2) for s, g in gap.items()}
    out["gap_side"] = "sell" if out["median_gap_pct"]["sell"] >= out["median_gap_pct"]["buy"] else "buy"
    bigger = [("sell" if abs(hb[h]["sell"] / ha[h]["sell"] - 1) >= abs(hb[h]["buy"] / ha[h]["buy"] - 1) else "buy") for h in hours]
    out["share_on_side"] = round(bigger.count(out["gap_side"]) / len(bigger), 3)
    ads = {v: [x[h]["ads"] for h in hours if "ads" in x[h]] for v, x in ((A, ha), (B, hb))}
    out["median_ads"] = {v: (st.median(a) if a else None) for v, a in ads.items()}
    if any(m is not None and m < THIN_ADS for m in out["median_ads"].values()):
        out["label"] = "one side thin"
    elif out["share_on_side"] > ALONE_SHARE:
        out["label"] = "one side moves alone"
    else:
        out["label"] = "unexplained"
    return out


def read_venue(path, source, wanted):
    """{ccy: [rows]} of the source_ok rows of one venue for the wanted currencies."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("source") == source and r.get("source_ok") == "True" and r["ccy"] in wanted:
                out.setdefault(r["ccy"], []).append(r)
    return out


def binance_min_orders(wanted):
    """{ccy: median min_order over the newest 168 hours of ads}, from data/p2p_ads.csv and data/p2p_ads/ (Binance only)."""
    per = {}
    for r in daily_csv.iter_dicts("p2p_ads", daily_csv.DATA, encoding="utf-8"):      # the closed p2p_ads.csv, then data/p2p_ads/<day>.csv
        if r["ccy"] in wanted and r.get("source_ok") == "True":
            v = fnum(r.get("min_order"))
            if v is not None:
                per.setdefault(r["ccy"], []).append((r["ts_utc"], v))
    out = {}
    for c, rows in per.items():
        newest = sorted({t[:13] for t, _ in rows})[-WINDOW_HOURS:]
        keep = [v for t, v in rows if t[:13] in newest]
        out[c] = st.median(keep) if keep else None
    return out


def build():
    pairs = json.load(open(os.path.join(DATA, "source_pairs.json")))
    flagged = {c: p for c, m in pairs["markets"].items() for p in m.get("pairs", []) if p.get("flag") and {p["a"], p["b"]} == {A, B}}
    a_rows = read_venue(os.path.join(DATA, "p2p_basis.csv"), A, flagged)
    b_rows = read_venue(os.path.join(DATA, "p2p_okx.csv"), B, flagged)
    mins = binance_min_orders(flagged)
    markets = {c: diagnose(a_rows.get(c, []), b_rows.get(c, []), mins.get(c), None) for c in sorted(flagged)}
    return {"as_of_utc": pairs["as_of_utc"], "window_hours": WINDOW_HOURS, "min_hours": MIN_HOURS, "markets": markets}


def rows_for(source, hours, buy, sell, ads):
    return [{"ts_utc": "2026-10-01T%02d:05:00+00:00" % h, "source": source, "ccy": "XXX", "buy_median": buy, "sell_median": sell, "n_ads": ads,
             "source_ok": "True"} for h in range(hours)]


def selftest():
    # the fake pair XXX: Binance sell 100, OKX sell 120 for 10 hours, 20 ads each, buy equal
    a = rows_for(A, 10, 100, 100, 20)
    b = rows_for(B, 10, 100, 120, 20)
    d = diagnose(a, b)
    assert d["label"] == "one side moves alone" and d["gap_side"] == "sell" and d["median_gap_pct"]["sell"] == 20.0, d
    thin = diagnose(a, rows_for(B, 10, 100, 120, 4))
    assert thin["label"] == "one side thin" and thin["median_ads"][B] == 4, thin
    few = diagnose(rows_for(A, 5, 100, 100, 20), rows_for(B, 5, 100, 120, 20))
    assert few["label"] == "not enough evidence" and few["hours"] == 5, few
    # the gap switches side hour by hour: not one side alone
    mixed_b = [dict(r, buy_median=(120 if i % 2 else 100), sell_median=(100 if i % 2 else 120)) for i, r in enumerate(rows_for(B, 10, 0, 0, 20))]
    assert diagnose(a, mixed_b)["label"] == "unexplained", diagnose(a, mixed_b)
    assert diagnose(a, [dict(r, buy_median="", sell_median="") for r in b])["label"] == "not enough evidence"
    print("diagnose_disagree self-test: ok")
    return 0


def main():
    if "--self-test" in sys.argv:
        return selftest()
    doc = build()
    with open(OUT, "w") as f:                              # persistence before display
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    labels = {}
    for m in doc["markets"].values():
        labels[m["label"]] = labels.get(m["label"], 0) + 1
    print("diagnose_disagree: %d flagged markets, %s" % (len(doc["markets"]), labels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
