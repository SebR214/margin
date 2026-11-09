#!/usr/bin/env python3
"""A third source for each flagged disagreement (BACKLOG 25a, SEB-301).

Takes each pair with flag true in the disagree list of data/gap_report.json, finds the newest price of every other source that
priced the same currency (the buy prices tools/emit_source_pairs.py compares: basis.csv, p2p_basis.csv, p2p_okx.csv), and says
which of the two the third source sits closer to, or 'no third source'. Writes data/disagree_arbiter.json. It names a nearer side,
it does not pick a right one; no price or status changes. Usage:
    python3 tools/disagree_arbiter.py
    python3 tools/disagree_arbiter.py --self-test
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emit_source_pairs as esp  # noqa: E402

DATA = os.path.join(os.path.dirname(HERE), "data")
OUT = os.path.join(DATA, "disagree_arbiter.json")


def arbitrate(pair, price_a, price_b, thirds):
    """pair: the gap_report entry. thirds: {source: newest price}. Returns one result entry."""
    out = {"ccy": pair["ccy"], "a": pair["a"], "b": pair["b"], "price_a": price_a, "price_b": price_b, "thirds": []}
    if not thirds or price_a is None or price_b is None:
        out["verdict"] = "no third source"
        return out
    closer = {"a": 0, "b": 0, "tie": 0}
    for name, p in sorted(thirds.items()):
        da, db = abs(p - price_a), abs(p - price_b)
        side = "a" if da < db else "b" if db < da else "tie"
        closer[side] += 1
        out["thirds"].append({"source": name, "price": p, "closer_to": side})
    if closer["a"] > closer["b"]:
        out["verdict"] = "closer to a"
    elif closer["b"] > closer["a"]:
        out["verdict"] = "closer to b"
    else:
        out["verdict"] = "no clear side"
    return out


def newest(series):
    """Newest (hour, price) of a {hour: price} series, or None."""
    if not series:
        return None
    h = max(series)
    return h, series[h]


def build(pairs, series):
    """series: {ccy: {source: {hour: price}}}. Each price is the source's newest real one."""
    results = []
    for p in pairs:
        if not p.get("flag"):
            continue
        src = series.get(p["ccy"], {})
        na, nb = newest(src.get(p["a"], {})), newest(src.get(p["b"], {}))
        thirds = {}
        for name, s in src.items():
            if name not in (p["a"], p["b"]) and newest(s):
                thirds[name] = newest(s)[1]
        results.append(arbitrate(p, na[1] if na else None, nb[1] if nb else None, thirds))
    return results


def self_test():
    pair = {"ccy": "XXX", "a": "a", "b": "b", "flag": True}
    def run(third):
        s = {"a": {"h": 100.0}, "b": {"h": 120.0}}
        if third is not None:
            s["c"] = {"h": third}
        return build([pair], {"XXX": s})[0]["verdict"]
    assert run(101.0) == "closer to a"
    assert run(119.0) == "closer to b"
    assert run(None) == "no third source"
    print("self-test ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    with open(os.path.join(DATA, "gap_report.json")) as f:
        pairs = json.load(f)["disagree"]
    basis, binance, okx = esp.read("basis.csv"), esp.read("p2p_basis.csv"), esp.read("p2p_okx.csv")
    if not binance:
        print("data/p2p_basis.csv has no rows", file=sys.stderr)
        return 1
    since = min(r["ts_utc"] for r in binance)[:13]
    results = build(pairs, esp.prices_by_source(basis, binance, okx, since))
    doc = {"as_of_utc": max(r["ts_utc"] for r in binance), "results": results}
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote data/disagree_arbiter.json: %d flagged pair(s), %d with a third source" % (
        len(results), sum(1 for r in results if r["thirds"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
