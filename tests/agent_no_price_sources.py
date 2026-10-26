#!/usr/bin/env python3
"""BACKLOG 17: tools/no_price_sources.py gives every country with no price one label from its fixed list, on made-up rows and on the
real CSVs.

  made-up rows (the script's own self-test)   -> each of the five labels comes out for the case built for it
  the real CSVs                               -> one entry per currency in index_latest.json without_value, each label from
                                                 the list, every board count a whole number, no ok_share above 1

    python3 tests/agent_no_price_sources.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import no_price_sources as nps  # noqa: E402


def main():
    assert nps.selftest() == 0
    out = os.path.join(HERE, "data", "no_price_sources.json")
    subprocess.run([sys.executable, os.path.join(HERE, "tools", "no_price_sources.py")], check=True, cwd=HERE,
                   stdout=subprocess.DEVNULL)
    got = json.load(open(out))
    idx = json.load(open(os.path.join(HERE, "data", "index_latest.json")))
    assert sorted(got["countries"]) == sorted(idx.get("without_value", [])), (sorted(got["countries"]), idx.get("without_value"))
    for c, r in got["countries"].items():
        assert r["label"] in nps.LABELS, (c, r["label"])
        for b, s in r["boards"].items():
            assert s["runs"] == int(s["runs"]) and 0 <= s["runs_ok"] <= s["runs"], (c, b, s)
            assert 0.0 <= s["ok_share"] <= 1.0, (c, b, s)
        assert set(r["boards_behind_label"]) <= set(r["boards"]), (c, r)
    print("agent_no_price_sources: ok, %d countries" % len(got["countries"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
