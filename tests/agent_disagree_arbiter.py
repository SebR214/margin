"""BACKLOG 25a: third-source arbiter on inline fixtures."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import disagree_arbiter as d


def verdict(third):
    pair = {"ccy": "XXX", "a": "a", "b": "b", "flag": True}
    s = {"a": {"2026-01-01T00": 100.0}, "b": {"2026-01-01T00": 120.0}}
    if third is not None:
        s["c"] = {"2026-01-01T00": third}
    out = d.build([pair, dict(pair, flag=False)], {"XXX": s})
    assert len(out) == 1, out
    return out[0]["verdict"]


def main():
    assert verdict(101.0) == "closer to a"
    assert verdict(119.0) == "closer to b"
    assert verdict(None) == "no third source"
    print("ok")


if __name__ == "__main__":
    main()
