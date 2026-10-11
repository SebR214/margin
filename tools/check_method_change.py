#!/usr/bin/env python3
"""A PR may not change how a published number is computed in silence (SEB-302).

If a PR changes the code of an emitter below, this runs the emitter twice on
the SAME data, once with the base branch's code and once with the PR's, and
compares what they publish. If any published number differs, the PR must also
change METHODOLOGY.md and bump INDEX_VERSION in tools/emit_countries.py.
A change that publishes the same numbers (a refactor, a new field, a comment)
passes without either.

Run by checks.yml on pull requests, from the BASE branch's copy of this file, so
a PR cannot edit its own judge.

    python3 tools/check_method_change.py --base origin/main
    python3 tools/check_method_change.py --self-test
"""
import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# emitter -> the published files it writes (globs under data/)
EMITTERS = {
    "tools/emit_countries.py": ["data/index_latest.json", "data/countries/*.json"],
    "tools/emit_routes.py": ["data/routes_hourly.json", "data/routes_summary.json", "data/routes_breakdown.json"],
    "tools/emit_findings.py": ["data/findings.json"],
}
VERSION_FILE = "tools/emit_countries.py"
VERSION_RE = re.compile(r'^INDEX_VERSION\s*=\s*"([^"]+)"', re.M)
# stamps and descriptive text are not published numbers: a reworded definition is not a method change
VOLATILE = {"computed_at", "as_of_utc", "generated_at", "last_recheck_utc", "definition", "definitions", "notes"}


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def diff_outputs(a_root, b_root, globs):
    """Files whose published content differs between two trees (volatile stamps ignored)."""
    names = set()
    for root in (a_root, b_root):
        for g in globs:
            names |= {os.path.relpath(p, root) for p in glob.glob(os.path.join(root, g)) if " " not in os.path.basename(p)}
    out = []
    for n in sorted(names):
        docs = []
        for root in (a_root, b_root):
            p = os.path.join(root, n)
            docs.append(strip(json.load(open(p))) if os.path.exists(p) else None)
        if docs[0] != docs[1]:
            out.append(n)
    return out


def decide(changed_files, differing, base_version, head_version):
    """(ok, reasons). Pure, so the test can feed it every case."""
    if not differing:
        return True, []
    reasons = []
    if "METHODOLOGY.md" not in changed_files:
        reasons.append("METHODOLOGY.md is not changed in this PR")
    if base_version == head_version:
        reasons.append("INDEX_VERSION is still %s" % head_version)
    if reasons:
        reasons.insert(0, "the published numbers in %d file(s) change, e.g. %s" % (len(differing), differing[0]))
    return not reasons, reasons


def version_of(text):
    m = VERSION_RE.search(text or "")
    return m.group(1) if m else None


def git(*args, cwd=ROOT, check=True):
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), r.stderr[-300:]))
    return r.stdout


def run_emitter(code_root, data_src, script):
    """Run `script` from code_root's checkout against a COPY of data_src; return the tree it ran in."""
    work = tempfile.mkdtemp(prefix="method-")
    for d in ("tools", "agents"):
        if os.path.isdir(os.path.join(code_root, d)):
            shutil.copytree(os.path.join(code_root, d), os.path.join(work, d),
                            ignore=shutil.ignore_patterns("* [0-9]*", "__pycache__"))
    for f in glob.glob(os.path.join(code_root, "*.py")) + glob.glob(os.path.join(code_root, "*.json")):
        if " " not in os.path.basename(f):
            shutil.copy(f, work)
    shutil.copytree(data_src, os.path.join(work, "data"), ignore=shutil.ignore_patterns("* [0-9].*"))
    r = subprocess.run([sys.executable, script], cwd=work, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise SystemExit("%s failed in %s: %s" % (script, code_root, (r.stderr or r.stdout)[-400:]))
    return work


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    changed = set(git("diff", "--name-only", "%s...HEAD" % a.base).split())
    todo = [e for e in EMITTERS if e in changed]
    if not todo:
        print("no published-number emitter changed")
        return 0
    base_tree = tempfile.mkdtemp(prefix="base-")
    git("worktree", "add", "-q", "--detach", base_tree, a.base)
    try:
        head_ver = version_of(open(os.path.join(ROOT, VERSION_FILE)).read())
        base_ver = version_of(git("show", "%s:%s" % (a.base, VERSION_FILE)))
        differing = []
        for script in todo:
            b = run_emitter(base_tree, os.path.join(ROOT, "data"), script)
            h = run_emitter(ROOT, os.path.join(ROOT, "data"), script)
            differing += ["%s (from %s)" % (n, script) for n in diff_outputs(b, h, EMITTERS[script])]
        ok, reasons = decide(changed, differing, base_ver, head_ver)
    finally:
        git("worktree", "remove", "--force", base_tree, check=False)
    if ok:
        print("method check: %s" % ("published numbers unchanged" if not differing else
              "published numbers change and METHODOLOGY.md and INDEX_VERSION (%s to %s) change with them" % (base_ver, head_ver)))
        return 0
    print("METHOD CHANGED IN SILENCE:\n- " + "\n- ".join(reasons))
    print("Files that differ:\n  " + "\n  ".join(differing[:20]))
    return 1


def self_test():
    # a. decide(): the four cases
    assert decide({"x.py"}, [], "1.2", "1.2") == (True, [])
    ok, why = decide({"tools/emit_countries.py"}, ["data/countries/XAF.json"], "1.2", "1.2")
    assert not ok and len(why) == 3, why
    ok, why = decide({"tools/emit_countries.py", "METHODOLOGY.md"}, ["a"], "1.2", "1.2")
    assert not ok and any("INDEX_VERSION" in w for w in why)
    ok, why = decide({"tools/emit_countries.py"}, ["a"], "1.2", "1.3")
    assert not ok and any("METHODOLOGY" in w for w in why)
    assert decide({"tools/emit_countries.py", "METHODOLOGY.md"}, ["a"], "1.2", "1.3") == (True, [])
    # b. diff_outputs(): a bad row (one country's number moved) is found; a new stamp is not
    with tempfile.TemporaryDirectory() as t:
        for side, pct, stamp in (("a", 5.4, "t1"), ("b", 5.4, "t2"), ("c", 7.6, "t1")):
            os.makedirs(os.path.join(t, side, "data", "countries"))
            json.dump({"index_pct": pct, "computed_at": stamp}, open(os.path.join(t, side, "data", "countries", "XAF.json"), "w"))
        g = ["data/countries/*.json"]
        assert diff_outputs(os.path.join(t, "a"), os.path.join(t, "b"), g) == [], "a new timestamp is not a method change"
        for side, text in (("a", "legs exist only for the base path"), ("b", "legs exist for every path priced")):
            json.dump({"index_pct": 5.4, "definition": {"path": text}}, open(os.path.join(t, side, "data", "countries", "ZZZ.json"), "w"))
        assert diff_outputs(os.path.join(t, "a"), os.path.join(t, "b"), g) == [], "reworded definition text is not a method change"
        for side in ("a", "b"):
            os.remove(os.path.join(t, side, "data", "countries", "ZZZ.json"))
        assert diff_outputs(os.path.join(t, "a"), os.path.join(t, "c"), g) == ["data/countries/XAF.json"]
    # c. version_of() reads the real file
    assert version_of(open(os.path.join(ROOT, VERSION_FILE)).read())
    assert version_of('INDEX_VERSION = "1.3"\n') == "1.3"
    print("check_method_change self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
