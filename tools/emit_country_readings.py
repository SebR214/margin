#!/usr/bin/env python3
"""data/country_readings/<CCY>/: every stored reading for a country, for its chart.

One reading = one price a source gave us at one moment, with the official rate
in force on that row, and the gap between them in percent:
    gap_pct = (price / official rate - 1) * 100

Files (months keep each file small and mean only the current month rewrites):
  data/country_readings/<CCY>/index.json
      {ccy, sources: [{id, kind, raw_file}], months: ["2026-08", ...],
       official: [[epoch_s, rate, source], ...]}      every fx row stored for the currency
  data/country_readings/<CCY>/<YYYY-MM>.json
      {ccy, month, columns: [...], readings: [[epoch_s, source_index, price,
       official_rate, gap_pct, n_ads, buy_ads_total], ...]}   oldest first

Sources read: data/basis.csv (order books and brokers, one row per venue and
hour, ask where there is one, else last price), data/p2p_basis.csv (Binance P2P
buy median) and data/p2p_okx.csv (OKX P2P buy median). n_ads is the number of
ads behind a P2P median. buy_ads_total is the number of buy-side ads on the
whole board that hour (data/p2p_depth.csv buy_total at the same timestamp), the
only per-reading depth the collector stores: it is a count of ads, not dollars.
It is null for order books, which store no size at all (dollar depth exists only
as the latest value in data/street_depth_latest.json). Rows with source_ok false are not readings. CriptoYa
aggregate rows ("CriptoYa (XXX)") are skipped, as in the index.

Stored values only: nothing is filled, carried over or estimated. Idempotent,
stdlib only, no wall clock.   Usage: python3 tools/emit_country_readings.py
"""

import csv
import datetime as dt
import json
import os
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "country_readings")
COLUMNS = ["epoch_s", "source", "price", "official_rate", "gap_pct", "n_ads", "buy_ads_total"]


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def epoch(ts):
    t = dt.datetime.fromisoformat(ts.strip())
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp())


def rows(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            yield r


def main():
    depth = {}
    for r in rows("p2p_depth.csv"):
        v = num(r.get("buy_total"))
        if v is not None:
            depth[(r["ccy"], r["ts_utc"][:16])] = v
    readings = {}   # ccy -> list of tuples
    sources = {}    # ccy -> {source: (kind, raw_file)}

    def add(ccy, ts, src, kind, raw_file, price, fx, n, dep):
        if not price or not fx:
            return
        readings.setdefault(ccy, []).append((epoch(ts), src, round(price, 6), round(fx, 6),
                                             round((price / fx - 1) * 100, 4), n, dep))
        sources.setdefault(ccy, {})[src] = (kind, raw_file)

    for r in rows("basis.csv"):
        if (r.get("source_ok") or "").strip().lower() != "true":
            continue
        v = r.get("venue") or ""
        if v.startswith("CriptoYa ("):
            continue
        price = num(r.get("usdt_ask")) or num(r.get("usdt_mid"))
        kind = "broker" if v.startswith("CriptoYa:") else "order_book"
        add(r["ccy"], r["ts_utc"], v, kind, "data/basis.csv", price, num(r.get("fx_mid_per_usd")), None, None)
    for name, label in (("p2p_basis.csv", "Binance P2P"), ("p2p_okx.csv", "OKX P2P")):
        for r in rows(name):
            if (r.get("source_ok") or "").strip().lower() != "true":
                continue
            n = num(r.get("n_ads"))
            add(r["ccy"], r["ts_utc"], label, "p2p", "data/" + name, num(r.get("buy_median")),
                num(r.get("fx_mid_per_usd")), int(n) if n is not None else None,
                depth.get((r["ccy"], r["ts_utc"][:16])) if label == "Binance P2P" else None)
    official = {}
    for r in rows("fx_rates.csv"):
        fx = num(r.get("fx_mid_per_usd"))
        if fx:
            official.setdefault(r["ccy"], []).append([epoch(r["ts_utc"]), round(fx, 6), r.get("source") or ""])

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    total = 0
    for ccy in sorted(set(readings) | set(official)):
        d = os.path.join(OUT, ccy)
        os.makedirs(d)
        src_names = sorted(sources.get(ccy, {}))
        idx = {s: i for i, s in enumerate(src_names)}
        by_month = {}
        for t, src, price, fx, gap, n, dep in sorted(readings.get(ccy, []), key=lambda x: (x[0], x[1])):
            m = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m")
            by_month.setdefault(m, []).append([t, idx[src], price, fx, gap, n, dep])
            total += 1
        for m, rs in by_month.items():
            with open(os.path.join(d, m + ".json"), "w") as f:
                json.dump({"ccy": ccy, "month": m, "columns": COLUMNS, "readings": rs}, f, separators=(",", ":"))
                f.write("\n")
        with open(os.path.join(d, "index.json"), "w") as f:
            json.dump({"ccy": ccy,
                       "sources": [{"id": s, "kind": sources[ccy][s][0], "raw_file": sources[ccy][s][1]} for s in src_names],
                       "months": sorted(by_month), "official": sorted(official.get(ccy, []))},
                      f, separators=(",", ":"))
            f.write("\n")
    print("country readings: %d readings across %d currencies" % (total, len(set(readings))))


if __name__ == "__main__":
    main()
