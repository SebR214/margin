#!/usr/bin/env python3
"""An invented market cannot feed the index (SEB-302). The test is a bad row.

    python3 tools/check_source_gate.py

Copies the stored data, adds one row from a venue that is not in
data/source_registry.json (a new "FakeEx" quoting the dollar 40% above the real
price in a market that has one source), and runs the real tools/emit_countries.py:
  1. unlisted, the fake venue changes nothing: the market's published number and its
     source count are exactly what they were without it;
  2. as a control, the same row with the venue approved DOES move the number, so the
     test would catch a gate that stopped working;
  3. with no registry at all the emitter fails loudly instead of publishing nothing.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CCY, REAL = "PHP", "Coins.ph"


def run(mutate):
    work = tempfile.mkdtemp(prefix="gate-")
    for d in ("tools", "agents"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(work, d), ignore=shutil.ignore_patterns("* [0-9]*", "__pycache__"))
    shutil.copytree(os.path.join(ROOT, "data"), os.path.join(work, "data"), ignore=shutil.ignore_patterns("* [0-9].*"))
    mutate(work)
    r = subprocess.run([sys.executable, "tools/emit_countries.py"], cwd=work, capture_output=True, text=True)
    return r, work


def add_fake_row(work, factor=1.4):
    p = os.path.join(work, "data", "basis.csv")
    raw = open(p, newline="").read().split("\n")
    hdr = next(csv.reader([raw[0]]))
    last = None
    for ln in raw[1:]:
        if ln.strip():
            r = dict(zip(hdr, next(csv.reader([ln.rstrip("\r")]))))
            if r["ccy"] == CCY and r["venue"] == REAL and r["source_ok"] == "True":
                last = r
    assert last, "no %s row to copy" % REAL
    fake = dict(last, venue="FakeEx", usdt_ask=str(float(last["usdt_ask"]) * factor), usdt_bid=str(float(last["usdt_bid"]) * factor),
                usdt_mid=str(float(last["usdt_mid"]) * factor), source="fakeex")
    with open(p, "a", newline="") as f:
        f.write("\n".join([] if raw[-1] == "" else [""]) + ",".join(fake[k] for k in hdr) + "\n")


def approve_fake(work):
    add_fake_row(work, 1.06)       # small enough not to be a sudden flip, so only the gate decides
    p = os.path.join(work, "data", "source_registry.json")
    reg = json.load(open(p))
    reg["sources"]["FakeEx"] = {"status": "approved", "basis": "test control"}
    json.dump(reg, open(p, "w"))


def country(work):
    d = json.load(open(os.path.join(work, "data", "index_latest.json")))
    return next(c for c in d["countries"] if c["ccy"] == CCY)


def main():
    r0, w0 = run(lambda w: None)
    assert r0.returncode == 0, r0.stderr[-300:]
    base = country(w0)
    r1, w1 = run(add_fake_row)
    assert r1.returncode == 0, r1.stderr[-300:]
    gated = country(w1)
    assert (gated["index_pct"], gated["n_sources"]) == (base["index_pct"], base["n_sources"]), (base, gated)
    r2, w2 = run(approve_fake)
    assert r2.returncode == 0, r2.stderr[-300:]
    moved = country(w2)
    assert moved["index_pct"] != base["index_pct"], "the control row must move the number, or this test proves nothing"
    r3, _ = run(lambda w: os.remove(os.path.join(w, "data", "source_registry.json")))
    assert r3.returncode != 0 and "source_registry" in (r3.stderr + r3.stdout), "no registry must fail loudly"
    print("source gate, bad row: %s %+.2f%% (%s source) unchanged with an unlisted FakeEx 40%% high; "
          "approved (at 6%% high) it moves to %+.2f%%; no registry fails loudly: ok" % (CCY, base["index_pct"], base["n_sources"], moved["index_pct"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
