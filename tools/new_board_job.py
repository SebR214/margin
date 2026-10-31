#!/usr/bin/env python3
"""Write the BACKLOG.md job for one board x currency, in the builder's form (SEB-422). No model, no network.

The research chat reads the table from `python3 tools/gap_report.py --boards` and runs this for the rows it picks:

    python3 tools/new_board_job.py bitget KES [--ads-seen 20] [--currency-id 34] [--min-ads 5]    # prints the item; append it to BACKLOG.md
    python3 tools/new_board_job.py --self-test

The job adds two new files and nothing else (a new board also adds its row to data/source_registry.json, already there for the five
boards that have a parser): collectors/board_configs/<board>_<ccy>.json and tests/agent_board_<board>_<ccy>.py. The done-when text
carries the exact content of both, so the builder copies rather than designs. collector_boards.py picks the config up on its next
hourly run; no collect.yml change.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
SIDES = {"binance": {"buy": "BUY", "sell": "SELL"}, "okx": {"buy": "sell", "sell": "buy"}, "kucoin": {"buy": "SELL", "sell": "BUY"},
         "bitget": {"buy": "1", "sell": "2"}, "htx": {"buy": "sell", "sell": "buy"}}
ENDPOINT = {"binance": "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search", "okx": "https://www.okx.com/v3/c2c/tradingOrders/books",
            "kucoin": "https://www.kucoin.com/_api/otc/ad/list", "bitget": "https://www.bitget.com/v1/p2p/pub/adv/queryAdvList",
            "htx": "https://www.htx.com/-/x/otc/v1/data/trade-market"}


def config(board, ccy, currency_id=None, min_ads=5):
    if board not in SIDES:
        raise SystemExit("no parser for %r (have %s)" % (board, ", ".join(sorted(SIDES))))
    if board == "htx" and not currency_id:
        raise SystemExit("htx needs --currency-id (the gap report prints it)")
    return {"board": board, "ccy": ccy, "pair": "USDT", "endpoint": ENDPOINT[board], "parser": board, "min_ads": min_ads,
            "sides": SIDES[board], "extra": ({"coin_id": 2, "currency_id": int(currency_id)} if board == "htx" else {})}


def next_number(text):
    nums = [int(m.group(1)) for m in re.finditer(r"^- \[[ x]\] (\d+)\.", text, re.M)]
    return max(nums or [0]) + 1


def job(board, ccy, n, ads_seen=None, currency_id=None, today="2026-10-31", min_ads=5):
    from collectors import template_board as tb
    name = "%s_%s" % (board, ccy)
    cfg = config(board, ccy, currency_id, int(min_ads))
    test = tb.new_test(name)
    seen = " (%s ads seen on page 1)" % ads_seen if ads_seen else ""
    done = ("python3 tests/agent_board_%s.py passes: the config file holds exactly this JSON, on one line: %s . The test file holds exactly "
            "this text (copy it, change nothing): <<<%s>>> . Nothing else in the repository changes; collector_boards.py reads the new config "
            "on its next hourly run." % (name, json.dumps(cfg), test.replace("\n", "\\n")))
    return (
        "- [ ] %d. Collect %s P2P for %s every hour\n"
        "  - [ ] %da. Add the %s x %s config and its test\n"
        "    track: aider\n"
        "    proposed: research chat %s (gap: board_gap_report: %s %s%s)\n"
        "    files: `collectors/board_configs/%s.json` `tests/agent_board_%s.py`\n"
        "    context: `collectors/template_board.py` `collectors/boards/%s.py` `data/source_registry.json`\n"
        "    done when: %s\n" % (n, board, ccy, n, board, ccy, today, board, ccy, seen, name, name, board, done))


def self_test():
    c = config("bitget", "KES")
    assert c["sides"] == {"buy": "1", "sell": "2"} and c["extra"] == {} and c["min_ads"] == 5
    assert config("htx", "KES", 34)["extra"] == {"coin_id": 2, "currency_id": 34}
    for bad in (lambda: config("bybit", "NGN"), lambda: config("htx", "KES")):
        try:
            bad()
            raise AssertionError("should refuse")
        except SystemExit:
            pass
    assert next_number("- [x] 3. a\n  - [x] 3a. b\n- [ ] 21. c\n") == 22
    sys.path.insert(0, ROOT)
    text = job("bitget", "KES", 99, 20)
    import job_shape
    import backlog
    items = backlog.parse(text)
    j = items[0]["jobs"][0]
    assert j["id"] == "99a" and j["files"] == ["collectors/board_configs/bitget_KES.json", "tests/agent_board_bitget_KES.py"], j
    assert job_shape.forbidden(j["files"], lambda p: False) == [], "the builder may take it"
    assert "tests/agent_board_bitget_KES.py" in text.split("done when:")[1]
    print("new_board_job self-test: ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--self-test" in a:
        self_test()
        sys.exit(0)
    if len(a) < 2:
        print(__doc__)
        sys.exit(2)
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    text = open(os.path.join(ROOT, "BACKLOG.md")).read()
    print(job(a[0], a[1], next_number(text), opt("--ads-seen"), opt("--currency-id"), min_ads=opt("--min-ads") or 5))
