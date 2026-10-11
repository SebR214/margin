#!/usr/bin/env python3
"""A sudden flip is held back, and the test proves it with a bad row (SEB-302, index v1.4).

    python3 tools/check_flip_hold.py            # unit cases, then a bad row through the real emitter
    python3 tools/check_flip_hold.py --unit     # unit cases only, no data needed

Unit cases feed tools/emit_countries.py's hold_decision() every outcome. The
integration case copies the stored data, adds ONE bad Binance row for a
person-to-person country (its price 1.6 times the real one, both sides, so it is
not crossed), runs the real tools/emit_countries.py on the copy, and checks the
country is withheld with a 'held back' reason and a normal row (1.02 times) is not.
"""
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import emit_countries as ec  # noqa: E402


def unit():
    H = dt.datetime(2026, 10, 11, 8, tzinfo=dt.timezone.utc)
    hours = [H - dt.timedelta(hours=k) for k in range(1, 7 * 24)]
    calm = {h: 5.0 + (0.2 if k % 2 else -0.2) for k, h in enumerate(hours)}       # median 5.0
    # a normal move
    assert ec.hold_decision(6.5, H, calm, {}, [])[0] == "ok"
    # a flip from +5 to -2: 7 points, over the 3-point bar
    assert ec.hold_decision(-2.0, H, calm, {}, [])[0] == "hold"
    # a sign change that is only 1 point is noise, not a flip
    near_zero = {h: 0.3 for h in hours}
    assert ec.hold_decision(-0.7, H, near_zero, {}, [])[0] == "ok"
    # a big jump at a high level needs a big move: 25% of 90 is 22.5 points
    high = {h: 90.0 for h in hours}
    assert ec.hold_decision(100.0, H, high, {}, [])[0] == "ok"
    assert ec.hold_decision(120.0, H, high, {}, [])[0] == "hold"
    # too little history: no judgement, the number stands
    assert ec.hold_decision(-9.0, H, {h: 5.0 for h in hours[:10]}, {}, [])[0] == "no_judgement"
    # a second source that agrees confirms at once; one that does not, does not
    assert ec.hold_decision(-2.0, H, calm, {}, [-1.5, -2.5])[0] == "confirmed_by_source"
    assert ec.hold_decision(-2.0, H, calm, {}, [-2.0, 5.0])[0] == "hold"
    # the same move held for the 3 hours before confirms it (held hours were never published, so they are absent from calm)
    gap = {H - dt.timedelta(hours=k) for k in (1, 2, 3)}
    calm3 = {h: v for h, v in calm.items() if h not in gap}
    held = {h: -2.0 for h in gap}
    assert ec.hold_decision(-2.0, H, calm3, held, [])[0] == "confirmed_by_time"
    # two hours is not enough, and a move the other way does not count
    two = {h: v for h, v in held.items() if h != H - dt.timedelta(hours=3)}
    assert ec.hold_decision(-2.0, H, calm3, two, [])[0] == "hold"
    wrong_way = {h: 12.0 for h in gap}
    assert ec.hold_decision(-2.0, H, calm3, wrong_way, [])[0] == "hold"
    print("flip hold, unit cases: ok")


def integration():
    idx = json.load(open(os.path.join(ROOT, "data", "index_latest.json")))
    doc = None
    for c in idx["countries"]:
        d = json.load(open(os.path.join(ROOT, "data", "countries", c["ccy"] + ".json")))
        if d.get("source_class") == "p2p_buy_median" and d.get("n_boards") == 1 and d.get("index_pct") is not None:
            doc = d
            break
    assert doc, "no single-board person-to-person country to test with"
    ccy = doc["ccy"]
    results = {}
    for factor in (1.6, 1.02):
        work = tempfile.mkdtemp(prefix="flip-")
        for d in ("tools", "agents"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(work, d), ignore=shutil.ignore_patterns("* [0-9]*", "__pycache__"))
        shutil.copytree(os.path.join(ROOT, "data"), os.path.join(work, "data"), ignore=shutil.ignore_patterns("* [0-9].*"))
        p = os.path.join(work, "data", "p2p_basis.csv")
        raw = open(p, newline="").read().split("\n")
        hdr = next(csv.reader([raw[0]]))
        last = None
        for ln in raw[1:]:
            if ln.strip():
                r = dict(zip(hdr, next(csv.reader([ln.rstrip("\r")]))))
                if r["ccy"] == ccy and r["source_ok"] == "True":
                    last = r
        t = dt.datetime.fromisoformat(last["ts_utc"]) + dt.timedelta(hours=1)
        bad = dict(last, ts_utc=t.isoformat(), buy_median=str(float(last["buy_median"]) * factor),
                   sell_median=str(float(last["sell_median"]) * factor), mid=str(float(last["mid"]) * factor), n_ads="20")
        with open(p, "a", newline="") as f:
            f.write("\n".join([""] if not raw[-1] == "" else []) + ",".join(
                '"%s"' % bad[k] if "," in bad[k] else bad[k] for k in hdr) + "\n")
        r = subprocess.run([sys.executable, "tools/emit_countries.py"], cwd=work, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-400:]
        out = json.load(open(os.path.join(work, "data", "index_latest.json")))
        held = [w for w in out["withheld"] if w["ccy"] == ccy]
        priced = [c for c in out["countries"] if c["ccy"] == ccy]
        results[factor] = (held, priced)
    held, priced = results[1.6]
    assert held and held[0]["reason_raw"].startswith("held back:") and not priced, results[1.6]
    assert held[0]["held_value"] > 20 and held[0]["baseline_pct"] is not None
    held2, priced2 = results[1.02]
    assert priced2 and not held2, "a 2% move is a normal row and must still be published"
    print("flip hold, bad row through the real emitter (%s, price x1.6): held back with %r; x1.02 published: ok" % (ccy, held[0]["reason_raw"][:70]))


if __name__ == "__main__":
    unit()
    if "--unit" not in sys.argv:
        integration()
