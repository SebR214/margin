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
It exits non-zero on either, so the PR does not merge itself, and prints why. A collector step that exits non-zero fails the check only
if it wrote no rows at all (31 Oct): one that wrote its rows and then exited 1 because an optional input was missing, like the
gas read of a USD->NGN or USD->INR sample, is printed as a warning. Such a sample row (errors starting "gas:missing") counts as answered. Nothing is written outside the scratch folder.
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
ANSWERED_BUT_REFUSED = re.compile(r"^(not enough evidence|no ads at|guard:|unsupported currency|implausible|ValueError:no ads|ValueError:unsupported)", re.I)
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


def gas_only_miss(r):
    """A corridor sample whose only failure is the optional gas reading (SEB-301, 31 Oct): collector.py writes the hour with the
    gas leg marked missing in `errors` and the corridor itself answered, so it still counts as a source that answered."""
    e = (r.get("errors") or "").strip()
    return e.startswith("gas:missing") and "; " not in e


def ok_keys(rows, cols, since=None):
    """Keys whose row says source_ok (or exists, when the file has no such column) at/after `since`."""
    got = set()
    for r in rows:
        if since and (r.get("ts_utc") or r.get("ts") or "") < since:
            continue
        flag = r.get("source_ok")
        if flag is not None and flag.strip().lower() != "true" and not ANSWERED_BUT_REFUSED.match((r.get("error") or "").strip()) \
                and not gas_only_miss(r):
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


def rows_in(scratch):
    """Data rows over every CSV in the scratch data folder (a file's first line is its header, not a row)."""
    n = 0
    for dirpath, _dirs, files in os.walk(os.path.join(scratch, "data")):
        for fn in files:
            if fn.endswith(".csv"):
                with open(os.path.join(dirpath, fn), "rb") as f:
                    n += max(f.read().count(b"\n") - 1, 0)
    return n


def run_steps(scratch, plan):
    """[(script, args, exit code, last 400 chars of output, rows the step wrote)]."""
    results = []
    for script, args in plan:
        if not os.path.exists(os.path.join(scratch, script)):
            results.append((script, args, 99, "script not in the branch", 0))
            continue
        before = rows_in(scratch)
        try:
            p = subprocess.run([sys.executable, script] + args, cwd=scratch, capture_output=True, text=True, timeout=STEP_TIMEOUT)
            results.append((script, args, p.returncode, (p.stderr or p.stdout)[-400:], rows_in(scratch) - before))
        except subprocess.TimeoutExpired:
            results.append((script, args, 124, "timed out after %d s" % STEP_TIMEOUT, rows_in(scratch) - before))
    return results


def step_failures(results):
    """The steps that fail the gate: those that exited non-zero AND wrote no rows at all (SEB-301, 31 Oct). A step that wrote its
    rows and then exited 1 because one optional input was missing (the gas read, a thin board) is a warning, not a failed gate."""
    return [r for r in results if r[2] != 0 and r[4] <= 0]


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
               {"ts_utc": "t", "source": "okx", "ccy": "BND", "source_ok": "False", "error": "guard: buy price 5 is 40 times the official rate"},
               {"ts_utc": "t", "source": "awx", "ccy": "MXN", "source_ok": "False", "error": "implausible:-5.31bps < 0.0bps floor (stale mid vs live quote)"}]
    assert ok_keys(refused, ("source", "ccy")) == {("okx", "XOF"), ("okx", "BND"), ("awx", "MXN")}, "a refused reading is an answer, a timeout is not"
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
    gasrow = {"corridor": "USD->INR", "source_ok": "False", "errors": "gas:missing:both RPCs"}
    assert ok_keys([gasrow], ("corridor",)) == {("USD->INR",)}, "a gas-only miss still answered"
    assert ok_keys([dict(gasrow, errors="gas:missing:x; mid:Timeout")], ("corridor",)) == set(), "any other failure still counts"
    assert ok_keys([dict(gasrow, errors="mid:Timeout")], ("corridor",)) == set()
    ok_step, warned, dead = ("a.py", [], 0, "", 5), ("b.py", [], 1, "gas:missing", 5), ("c.py", [], 1, "boom", 0)
    assert step_failures([ok_step, warned, dead]) == [dead], "exit 1 with rows written is a warning; exit 1 with no rows fails"
    assert step_failures([("d.py", [], 99, "script not in the branch", 0)]) != [], "a script that is not there fails"
    with tempfile.TemporaryDirectory() as t:
        os.makedirs(os.path.join(t, "data", "sub"))
        assert rows_in(t) == 0
        with open(os.path.join(t, "data", "x.csv"), "w") as f:
            f.write("h\n1\n2\n")
        with open(os.path.join(t, "data", "sub", "y.csv"), "w") as f:
            f.write("h\n")
        assert rows_in(t) == 2, rows_in(t)
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
        failed = step_failures(results)
        for script, args, code, tail, wrote in results:
            print("  %-26s %-22s exit %s, %d rows%s" % (script, " ".join(args), code, wrote,
                                                        "  (exit non-zero but rows written: a warning, not a failure)" if code != 0 and wrote > 0 else ""))
        bad, missing = judge(scratch, headers, ROOT)
        for attempt in range(RETRIES):
            if not missing:
                break
            print("\n%d source(s) did not answer; one more full pass (an exchange can blink): %s" % (len(missing), "; ".join(missing)[:300]))
            more = run_steps(scratch, plan)
            failed = step_failures(more)
            bad, missing = judge(scratch, headers, ROOT)        # the rows of both passes are in the scratch files
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    problems = bad + missing
    if failed:
        problems += ["%s %s exited %s and wrote no rows: %s" % (s, " ".join(a), c, t.strip()[-200:]) for s, a, c, t, _w in failed]
    if problems:
        print("\nCOLLECTION RUN FAILED:\n- " + "\n- ".join(problems[:40]))
        return 1
    print("\ncollection run ok: every step exited 0, no file's columns changed, every source that answers on main answers here")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
