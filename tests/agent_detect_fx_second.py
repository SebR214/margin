#!/usr/bin/env python3
"""SEB-466: the event detector uses Frankfurter (data/fx_second.csv) as a second official source. Fixed rows, no live data.

  both move      er-api and Frankfurter both step 3% or more the same way: "two sources", naming frankfurter-v2.
  one moves      er-api steps 12% and Frankfurter stays flat: a data warning that names the second source, never an event.
  no second data no Frankfurter rows for the currency: the old answer stands ("one source").

    python3 tests/agent_detect_fx_second.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import detect_events as de  # noqa: E402

D = "2026-11-10"
B = de.day_add(D, -de.OFFICIAL_DAYS)


def data_with(second, live=None):
    return {"off": {"XXX": {B: 100.0, D: 88.0}}, "live": {"XXX": live or {}}, "second": {"XXX": second}, "central_bank": {"XXX"}}


ch = de.pct(100.0, 88.0)

# both move
d = data_with({B: 500.0, D: 440.0})
assert de.confirmation("official_break", d, "XXX", D, ch) == ("two sources", ["er-api", "frankfurter-v2"]), "both move"
assert de.unit_error(d, "XXX", D, ch) is None, "both move: no warning"

# one moves
d = data_with({B: 500.0, D: 501.0})
assert de.confirmation("official_break", d, "XXX", D, ch) == ("one source", ["er-api"]), "one moves: still one source"
why = de.unit_error(d, "XXX", D, ch)
assert why and "frankfurter-v2" in why and "second official source did not" in why, "one moves: warning names the second source: %r" % why

# no second data
d = data_with({})
assert de.confirmation("official_break", d, "XXX", D, ch) == ("one source", ["er-api"]), "no second data"
assert de.unit_error(d, "XXX", D, ch) is None, "no second data: nothing to contradict the step"

# the live rate alone keeps its old wording
d = data_with({}, live={B: 100.0, D: 99.0})
assert de.unit_error(d, "XXX", D, ch).endswith("did not (%s%%)" % de.pct(100.0, 99.0)), "live-only wording"

# a step the live rate shows is still confirmed when Frankfurter has no rows
d = data_with({}, live={B: 100.0, D: 88.0})
assert de.confirmation("official_break", d, "XXX", D, ch) == ("two sources", ["er-api", "fx_live"]), "live still confirms"
print("ok: detect_events with fx_second, 5 cases")
