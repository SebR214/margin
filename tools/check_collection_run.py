#!/usr/bin/env python3
"""One full collection run on a branch (SEB-301, Seb's merge rule of 20 Oct). No model.

    python3 tools/check_collection_run.py [--only-parse]
    python3 tools/check_collection_run.py --self-test

Run in CI on a PR that touches collection code. It copies the code and the small files of this checkout into a scratch folder with
every data CSV reduced to its header line (so nothing is appended to the real data), runs every collector step named in
.github/workflows/collect.yml, in order, there, and then judges the new rows:
  1. no CSV gains a row whose column count differs from its header (an existing file's columns must not change);
  2. every source that answered in each of main's last 3 committed collections (data/*.csv in this checkout, where source_ok is
     true) answers again in this run. A source missing or not ok on the branch fails the check and is named.
It exits non-zero on either, so the PR does not merge itself, and prints why. Nothing is written outside the scratch folder.
Sources are keyed per file: basis.csv by venue and currency, p2p_basis.csv and p2p_okx.csv by source and currency,
provider_quotes.csv by corridor and provider, stable_venues.csv and samples.csv by corridor, fx_rates.csv by currency (present = ok).
"""
import collections
import csv
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = {
    "basis.csv": ("venue", "ccy"),
    "p2p_basis.csv": ("source", "ccy"),
    "p2p_okx.csv": ("source", "ccy"),
    "provider_quotes.csv": ("corridor", "provider"),
    "stable_venues.csv": ("corridor",),
    "samples.csv": ("corridor",),
    "fx_rates.csv": ("ccy",),
}
STEP = re.compile(r"^\s*run:\s*python3\s+(collector[\w]*\.py)((?:\s+--corridor\s+\"[^\"]+\")?)\s*$", re.M)
# A row that says the source ANSWERED but the market or the guard refused the reading (a crossed board, too few ads, an unsupported
# currency) is an answer. Only a failed pull (timeout, HTTP error, bad JSON, no row at all) counts as a source that did not answer.
ANSWERED_BUT_REFUSED = re.compile(r"^(not enough evidence|no ads at|guard:|unsupported currency|ValueError:no ads|ValueError:unsupported)", re.I)
HOURS_BACK = 3
RETRIES = 1                 # one more full pass when a source is missing, before the check fails: an exchange can blink
STEP_TIMEOUT = 20 * 60


def steps(yml_text):
    """[(script, [args])] in file order, from the collect.yml `run: python3 collector...` lines."""
    out = []
    for m in STEP.finditer(yml_text):
        args = re.findall(r"--corridor\s+\"([^\"]+)\"", m.group(2))
        out.append((m.group(1), ["--corridor", args[0]] if args else []))
    return out


def ok_keys(rows, cols, since=None):
    """Keys whose row says source_ok (or exists, when the file has no such column) at/after `since`."""
    got = set()
    for r in rows:
        if since and (r.get("ts_utc") or r.get("ts") or "") < since:
            continue
        flag = r.get("source_ok")
        if flag is not None and flag.strip().lower() != "true" and not ANSWERED_BUT_REFUSED.match((r.get("error") or "").strip()):
            continue
        got.add(tuple(r.get(c, "") for c in cols))
    return got


def main_stable(name, path, hours=HOURS_BACK):
    """Keys that were ok in each of the last `hours` hourly collections of the committed file (the last `hours` distinct hours)."""
    if not os.path.exists(path):
        return set()
    cols = KEYS[name]
    by_hour = collections.OrderedDict()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            h = (r.get("ts_utc") or r.get("ts") or "")[:13]
            by_hour.setdefault(h, []).append(r)
    last = list(by_hour)[-hours:]
    sets = [ok_keys(by_hour[h], cols) for h in last]
    return set.intersection(*sets) if sets else set()


def prepare(root):
    scratch = tempfile.mkdtemp(prefix="collect-run-")
    for entry in os.listdir(root):
        if entry in (".git", "data", "node_modules") or entry.startswith("."):
            continue
        src = os.path.join(root, entry)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(scratch, entry), ignore=shutil.ignore_patterns("* [0-9]*", "__pycache__"))
        elif " " not in entry:
            shutil.copy(src, scratch)
    shutil.copytree(os.path.join(root, ".github"), os.path.join(scratch, ".github"), ignore=shutil.ignore_patterns("* [0-9]*"))
    data = os.path.join(scratch, "data")
    os.makedirs(data)
    headers = {}
    for dirpath, _, files in os.walk(os.path.join(root, "data")):
        rel = os.path.relpath(dirpath, os.path.join(root, "data"))
        os.makedirs(os.path.join(data, rel), exist_ok=True)
        for fn in files:
            if " " in fn:
                continue
            src = os.path.join(dirpath, fn)
            dst = os.path.join(data, rel, fn)
            if fn.endswith(".csv"):
                with open(src, newline="") as f:
                    first = f.readline()
                with open(dst, "w", newline="") as g:
                    g.write(first)
                headers[os.path.normpath(os.path.join(rel, fn))] = first.strip()
            elif os.path.getsize(src) < 5_000_000:
                shutil.copy(src, dst)
    return scratch, headers


def run_steps(scratch, plan):
    results = []
    for script, args in plan:
        if not os.path.exists(os.path.join(scratch, script)):
            results.append((script, args, 99, "script not in the branch"))
            continue
        try:
            p = subprocess.run([sys.executable, script] + args, cwd=scratch, capture_output=True, text=True, timeout=STEP_TIMEOUT)
            results.append((script, args, p.returncode, (p.stderr or p.stdout)[-400:]))
        except subprocess.TimeoutExpired:
            results.append((script, args, 124, "timed out after %d s" % STEP_TIMEOUT))
    return results


def judge(scratch, headers, root):
    bad = []
    for rel, head in headers.items():
        path = os.path.join(scratch, "data", rel)
        if not os.path.exists(path):
            continue
        with open(path, newline="") as f:
            rd = csv.reader(f)
            first = next(rd, [])
            if ",".join(first) != head and head:
                bad.append("%s: the header line changed" % rel)
                continue
            for n, row in enumerate(rd, 2):
                if len(row) != len(first):
                    bad.append("%s line %d: %d columns, header has %d" % (rel, n, len(row), len(first)))
                    break
    missing = []
    for name, cols in KEYS.items():
        before = main_stable(name, os.path.join(root, "data", name))
        path = os.path.join(scratch, "data", name)
        after = set()
        if os.path.exists(path):
            with open(path, newline="") as f:
                after = ok_keys(list(csv.DictReader(f)), cols)
        for k in sorted(before - after):
            missing.append("%s %s answers on main and not on this branch" % (name, "/".join(k)))
    return bad, missing


def self_test():
    yml = '''
      - name: a
        run: python3 collector.py
      - name: b
        run: python3 collector.py --corridor "USD->MXN"
      - name: c
        run: python3 collector_basis.py
      - name: d
        run: python3 tools/emit_latest.py
'''
    assert steps(yml) == [("collector.py", []), ("collector.py", ["--corridor", "USD->MXN"]), ("collector_basis.py", [])]
    rows = [{"ts_utc": "t", "venue": "A", "ccy": "X", "source_ok": "True"}, {"ts_utc": "t", "venue": "B", "ccy": "X", "source_ok": "False"}]
    assert ok_keys(rows, ("venue", "ccy")) == {("A", "X")}
    refused = [{"ts_utc": "t", "source": "okx", "ccy": "XOF", "source_ok": "False", "error": "not enough evidence this hour: the buy side is below the sell side"},
               {"ts_utc": "t", "source": "okx", "ccy": "AOA", "source_ok": "False", "error": "ReadTimeout: read timed out"},
               {"ts_utc": "t", "source": "okx", "ccy": "BND", "source_ok": "False", "error": "guard: buy price 5 is 40 times the official rate"}]
    assert ok_keys(refused, ("source", "ccy")) == {("okx", "XOF"), ("okx", "BND")}, "a refused reading is an answer, a timeout is not"
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "basis.csv")
        with open(p, "w") as f:
            f.write("ts_utc,venue,ccy,source_ok\n")
            for h in ("2026-10-20T01", "2026-10-20T02", "2026-10-20T03", "2026-10-20T04"):
                f.write("%s:06,A,X,True\n" % h)
                f.write("%s:06,B,X,%s\n" % (h, "True" if h != "2026-10-20T03" else "False"))
        assert main_stable("basis.csv", p) == {("A", "X")}, "B failed in one of the last 3 hours, so it is not held against a branch"
    scratch, headers = prepare(ROOT)
    try:
        assert "basis.csv" in headers and headers["basis.csv"].startswith("ts_utc,venue")
        assert os.path.getsize(os.path.join(scratch, "data", "basis.csv")) < 200
        bad, miss = judge(scratch, headers, ROOT)
        assert not bad, bad
        assert miss, "an empty run must be reported as missing every source that answers on main"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("check_collection_run self-test: ok")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    plan = steps(open(os.path.join(ROOT, ".github", "workflows", "collect.yml")).read())
    print("collector steps from collect.yml: %d" % len(plan))
    if "--only-parse" in argv:
        for s, a in plan:
            print(" ", s, " ".join(a))
        return 0
    scratch, headers = prepare(ROOT)
    try:
        results = run_steps(scratch, plan)
        failed = [r for r in results if r[2] != 0]
        for script, args, code, tail in results:
            print("  %-26s %-22s exit %s" % (script, " ".join(args), code))
        bad, missing = judge(scratch, headers, ROOT)
        for attempt in range(RETRIES):
            if not missing:
                break
            print("\n%d source(s) did not answer; one more full pass (an exchange can blink): %s" % (len(missing), "; ".join(missing)[:300]))
            more = run_steps(scratch, plan)
            failed = [r for r in more if r[2] != 0]
            bad, missing = judge(scratch, headers, ROOT)        # the rows of both passes are in the scratch files
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    problems = bad + missing
    if failed:
        problems += ["%s %s exited %s: %s" % (s, " ".join(a), c, t.strip()[-200:]) for s, a, c, t in failed]
    if problems:
        print("\nCOLLECTION RUN FAILED:\n- " + "\n- ".join(problems[:40]))
        return 1
    print("\ncollection run ok: every step exited 0, no file's columns changed, every source that answers on main answers here")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
