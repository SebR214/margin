#!/usr/bin/env python3
"""A pair we model as stable-priced that stops being one fails the fee check loudly (SEB-310, 22 Oct).

Coinbase's public products endpoint carries `fx_stablecoin` per pair. USDT-USD lost stablecoin fee pricing on 1 May 2025, which
the config did not know until 22 Oct 2026: its on-ramp fee read 1 bp instead of 60. This feeds check_fees.check_stable_pricing
every case with a fixed answer, offline:

  modelled stable-priced, endpoint says false   -> pricing_changed (the failure that was missed)
  modelled standard fees, endpoint says false   -> ok
  modelled standard fees, endpoint says true    -> pricing_changed (a pair that regained stable pricing: the fee is too high)
  endpoint answer without the flag, or a failed fetch -> parse_fail, never ok
and that every Coinbase on-ramp in collector.CORRIDORS names its pair and what it models, so the check reads every one of them.

    python3 tests/check_stable_pair.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_fees as cf  # noqa: E402
import collector  # noqa: E402

TS = "2026-10-22T00:00:00Z"


def fixed(payload):
    return lambda url: payload


def boom(url):
    raise OSError("blocked")


assert cf.check_stable_pricing(TS, "USDT-USD", True, 1.0, fixed({"fx_stablecoin": False}))["status"] == "pricing_changed"
assert cf.check_stable_pricing(TS, "USDT-USD", False, 60.0, fixed({"fx_stablecoin": False}))["status"] == "ok"
assert cf.check_stable_pricing(TS, "USDT-USD", False, 60.0, fixed({"fx_stablecoin": True}))["status"] == "pricing_changed"
assert cf.check_stable_pricing(TS, "USDT-USD", True, 1.0, fixed({"fx_stablecoin": True}))["status"] == "ok"
assert cf.check_stable_pricing(TS, "USDT-USD", False, 60.0, fixed({"id": "USDT-USD"}))["status"] == "parse_fail"
assert cf.check_stable_pricing(TS, "USDT-USD", False, 60.0, fixed({"fx_stablecoin": "false"}))["status"] == "parse_fail"
assert cf.check_stable_pricing(TS, "USDT-USD", False, 60.0, boom)["status"] == "parse_fail"

coinbase = [c for c, cfg in collector.CORRIDORS.items() if (cfg.get("onramp") or {}).get("venue") == "Coinbase"]
assert coinbase, "no Coinbase on-ramp found"
for c in coinbase:
    on = collector.CORRIDORS[c]["onramp"]
    assert on.get("pair") and isinstance(on.get("stable_priced"), bool), c + ": the on-ramp must name its pair and whether it is stable-priced"
    assert (on["taker_bps"] <= 1.0) == on["stable_priced"], c + ": the fee and the stable_priced flag disagree"
rows = cf.coinbase_pair_rows(TS, fixed({"fx_stablecoin": False}))
assert [r["regime"] for r in rows] == ["stable_pair:USDT-USD"] and rows[0]["status"] == "ok", rows
rows = cf.coinbase_pair_rows(TS, fixed({"fx_stablecoin": True}))
assert rows[0]["status"] == "pricing_changed", rows
print("check_stable_pair: ok (a pair that loses or regains stable pricing fails the fee check, a broken answer is never ok)")
