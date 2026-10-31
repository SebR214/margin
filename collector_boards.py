#!/usr/bin/env python3
"""Every board x currency in collectors/board_configs/, once an hour (SEB-422, lever 1). No model.

Runs collectors/template_board.py for each config file. Rows go to the daily tables p2p_board_ads and p2p_ads_sellers (tools/daily_csv.py,
in margin-data once the raw tables have moved) and to data/p2p_basis_boards.csv. The tables are written before anything is printed.
Exits non-zero when no config was read, or when a config names a board that has no row in data/source_registry.json. A config that
fails is a row with source_ok false and the reason; the run goes on to the next.

Usage:  python3 collector_boards.py             # one pass
        python3 collector_boards.py --selftest   # parsers and rows on fixtures, no network, writes nothing
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collectors import template_board as tb  # noqa: E402
import daily_csv  # noqa: E402
import collector_p2p_sellers as sellers  # noqa: E402

TIME_BUDGET = 420


def main(argv):
    if "--selftest" in argv:
        return tb.selftest()
    cfgs = tb.load_all()
    if not cfgs:
        print("collector_boards: no configs in collectors/board_configs/", file=sys.stderr)
        return 1
    bad = tb.registry_problems(cfgs)
    if bad:
        for b in bad:
            print("collector_boards: " + b, file=sys.stderr)
        return 1
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    deadline = dt.datetime.now().timestamp() + TIME_BUDGET
    ad_rows, seller_rows, basis = [], [], []
    for cfg in cfgs:
        if dt.datetime.now().timestamp() > deadline:
            basis.append({"ts_utc": ts, "board": cfg["board"], "ccy": cfg["ccy"], "buy_median": "", "sell_median": "", "n_ads": 0,
                          "source_ok": False, "error": "time budget used before this config was read"})
            continue
        a, s, b = tb.collect_config(cfg, ts)
        ad_rows += a
        seller_rows += s
        basis.append(b)
    daily_csv.append(tb.ADS, tb.ADS_FIELDS, ad_rows)                      # written before anything is printed
    daily_csv.append(sellers.NAME, sellers.HEADER, seller_rows)
    tb.write_basis(basis)
    ok = sum(1 for b in basis if b["source_ok"])
    print("collector_boards: %d of %d configs read, %d ads" % (ok, len(basis), len(ad_rows)))
    for b in basis:
        if not b["source_ok"]:
            print("  %s %s: %s" % (b["board"], b["ccy"], b["error"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
