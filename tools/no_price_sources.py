#!/usr/bin/env python3
"""One line per country with no price: which stored board was checked, and why none gives a price (BACKLOG 17, SEB-301).

The countries are the ones data/index_latest.json lists under `without_value` this hour. For each, every board we already store
is read over the newest WINDOW_HOURS hours of its own file:

    binance_p2p   data/p2p_basis.csv   (rows with source binance_p2p)
    okx_p2p       data/p2p_okx.csv
    KuCoin P2P    data/p2p_kucoin.csv
    VALR          data/zar_valr.csv
    Luno ZAR      data/zar_luno.csv

Per board: runs in the window, runs with source_ok true, the median and largest n_ads, the newest error, and its status in
data/source_registry.json. One label per country, chosen by code in this order:

    'another approved board answers'       an approved board other than binance_p2p was source_ok in at least OK_SHARE of its runs
    'a board in quarantine answers'        a board in quarantine was source_ok in at least OK_SHARE of its runs

source_ok is each board's own rule (some ads near USD 500), not the 10 buy-side ads the published price needs, so the first two
labels say where a second look is worth it, not that a price exists.
    'boards have ads, too few'             some board listed at least one ad in the window
    'no stored board has ads'              boards answered, none listed an ad
    'no stored board lists it'             no board has a row for this currency in the window

Writes data/no_price_sources.json. A report, not a price: nothing reads it, no published number or source status changes.

    python3 tools/no_price_sources.py              # writes data/no_price_sources.json and prints one line per country
    python3 tools/no_price_sources.py --self-test
"""
import csv
import json
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "no_price_sources.json")
WINDOW_HOURS = 168
OK_SHARE = 0.9
PRICED_FROM = "binance_p2p"

# board name -> (file, column naming the board, value in that column or None for every row)
BOARDS = [
    ("binance_p2p", "p2p_basis.csv", "source", "binance_p2p"),
    ("okx_p2p", "p2p_okx.csv", "source", "okx_p2p"),
    ("KuCoin P2P", "p2p_kucoin.csv", "venue", "KuCoin P2P"),
    ("VALR", "zar_valr.csv", "venue", "VALR"),
    ("Luno ZAR", "zar_luno.csv", "venue", "Luno ZAR"),
]
LABELS = ["another approved board answers", "a board in quarantine answers", "boards have ads, too few",
          "no stored board has ads", "no stored board lists it"]


def ts(s):
    s = s.strip().replace("Z", "+00:00")
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_board(path, col, val, ccys):
    """{ccy: [(ts, ok, n_ads, error)]} for the currencies asked, every row of the file. Missing file is an empty dict."""
    out = {c: [] for c in ccys}
    if not os.path.exists(path):
        return out
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            c = r.get("ccy")
            if c not in out or (val is not None and r.get(col) != val):
                continue
            out[c].append((ts(r["ts_utc"]), r.get("source_ok") == "True", num(r.get("n_ads")), (r.get("error") or "")[:120]))
    return out


def summarise(rows, end):
    """Counts over the WINDOW_HOURS before `end`, or None when the board has no row in the window."""
    start = end - timedelta(hours=WINDOW_HOURS)
    w = [x for x in rows if start < x[0] <= end]
    if not w:
        return None
    ads = [x[2] for x in w if x[2] is not None]
    errs = [x for x in w if x[3]]
    return {"runs": len(w), "runs_ok": sum(1 for x in w if x[1]), "ok_share": round(sum(1 for x in w if x[1]) / len(w), 3),
            "median_ads": round(st.median(ads), 1) if ads else None, "max_ads": max(ads) if ads else None,
            "last_run": max(x[0] for x in w).strftime("%Y-%m-%dT%H:%MZ"), "last_error": errs[-1][3] if errs else ""}


def label(boards, status):
    """The label chosen by code, from the per-board summaries and the registry status of each board."""
    seen = {b: s for b, s in boards.items() if s is not None}
    if not seen:
        return LABELS[4], []
    good = [b for b, s in seen.items() if s["ok_share"] >= OK_SHARE]
    other = sorted(b for b in good if b != PRICED_FROM and status.get(b) == "approved")
    if other:
        return LABELS[0], other
    quar = sorted(b for b in good if status.get(b) == "quarantine")
    if quar:
        return LABELS[1], quar
    some = sorted(b for b, s in seen.items() if (s["max_ads"] or 0) > 0)
    if some:
        return LABELS[2], some
    return LABELS[3], sorted(seen)


def build(index, registry, board_rows, end):
    status = {k: v.get("status") for k, v in registry.get("sources", {}).items()}
    reasons = {w["ccy"]: (w.get("country"), w.get("reason_raw") or w.get("reason")) for w in index.get("withheld", [])}
    out = {}
    for c in index.get("without_value", []):
        boards = {b: summarise(board_rows[b].get(c, []), end) for b in board_rows}
        lab, which = label(boards, status)
        out[c] = {"country": reasons.get(c, (None, None))[0], "published_reason": reasons.get(c, (None, None))[1],
                  "label": lab, "boards_behind_label": which,
                  "boards": {b: dict(s, status=status.get(b)) for b, s in boards.items() if s is not None}}
    return out


def line(c, r):
    which = ", ".join(r["boards_behind_label"])
    return "%s %s: %s%s" % (c, r["country"] or "", r["label"], (" (%s)" % which) if which else "")


def main():
    index = json.load(open(os.path.join(DATA, "index_latest.json")))
    registry = json.load(open(os.path.join(DATA, "source_registry.json")))
    ccys = list(index.get("without_value", []))
    if not ccys:
        print("no_price_sources: no country is without a price this hour")
    board_rows = {b: read_board(os.path.join(DATA, f), col, val, ccys) for b, f, col, val in BOARDS}
    end = ts(index["as_of_utc"]) if index.get("as_of_utc") else datetime.now(timezone.utc)
    end = max([end] + [x[0] for rows in board_rows.values() for v in rows.values() for x in v])
    res = {"as_of_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_hours": WINDOW_HOURS, "ok_share": OK_SHARE,
           "priced_from": PRICED_FROM, "source_files": ["data/index_latest.json", "data/source_registry.json"] +
           ["data/" + f for _, f, _, _ in BOARDS], "countries": build(index, registry, board_rows, end)}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, OUT)
    for c, r in res["countries"].items():
        print(line(c, r))
    return 0


def selftest():
    t0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
    hours = [t0 + timedelta(hours=i) for i in range(20)]
    reg = {"sources": {"binance_p2p": {"status": "approved"}, "okx_p2p": {"status": "approved"}, "VALR": {"status": "quarantine"}}}
    rows = {"binance_p2p": {"AAA": [(h, False, 4.0, "too few") for h in hours], "BBB": [(h, False, 3.0, "x") for h in hours],
                            "CCC": [(h, False, 2.0, "x") for h in hours], "DDD": [(h, False, 0.0, "x") for h in hours]},
            "okx_p2p": {"AAA": [(h, True, 18.0, "") for h in hours], "BBB": [(h, h.hour % 2 == 0, 12.0, "") for h in hours]},
            "VALR": {"BBB": [(h, True, 80.0, "") for h in hours]}}
    idx = {"without_value": ["AAA", "BBB", "CCC", "DDD", "EEE"], "withheld": [{"ccy": "AAA", "country": "A", "reason_raw": "r"}]}
    got = build(idx, reg, rows, hours[-1])
    want = {"AAA": (LABELS[0], ["okx_p2p"]), "BBB": (LABELS[1], ["VALR"]), "CCC": (LABELS[2], ["binance_p2p"]),
            "DDD": (LABELS[3], ["binance_p2p"]), "EEE": (LABELS[4], [])}
    for c, (lab, which) in want.items():
        assert (got[c]["label"], got[c]["boards_behind_label"]) == (lab, which), (c, got[c])
    assert got["AAA"]["boards"]["okx_p2p"]["runs"] == 20 and got["AAA"]["published_reason"] == "r", got["AAA"]
    old = build(idx, reg, rows, hours[-1] + timedelta(hours=WINDOW_HOURS + 1))
    assert all(v["label"] == LABELS[4] for v in old.values()), old
    print("no_price_sources self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--self-test" in sys.argv else main())
