#!/usr/bin/env python3
"""Run every test an agent job added: tests/agent_*.py (SEB-301, 25 Oct). No model, no network.

Each researcher job lists one new test file, tests/agent_<name>.py, and its `done when:` names it. This one step in checks.yml runs all of
them, so a new test is part of CI and of the Aider builder's test command (tools/aider_checks.py) without editing checks.yml.

    python3 tools/run_agent_tests.py
"""
import ast
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hollow(src):
    """Why a test proves nothing, or None. An empty file exits 0, so #701 (Bybit, 28 Oct) merged three empty files and passed."""
    if not src.strip():
        return "is empty"
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None     # running it fails it
    if not any(isinstance(n, ast.Assert) for n in ast.walk(tree)):
        return "has no assert"
    return None


def self_test():
    assert hollow("") == "is empty" and hollow(" \n\n") == "is empty"
    assert hollow("print('ok')\n") == "has no assert"
    assert hollow("# assert x\nprint('assert')\n") == "has no assert", "a comment or a string is not an assert"
    assert hollow("x = 1\nassert x == 1\n") is None
    assert hollow("def t():\n    assert 1\nt()\n") is None
    print("run_agent_tests self-test: ok")


def main(argv=()):
    if "--self-test" in argv:
        self_test()
        return 0
    tests = sorted(glob.glob(os.path.join(ROOT, "tests", "agent_*.py")))
    bad = []
    for t in tests:
        rel = os.path.relpath(t, ROOT)
        with open(t) as f:
            why = hollow(f.read())
        if why:
            print("FAIL %s" % rel)
            bad.append("%s %s: a test that asserts nothing passes whatever the code does" % (rel, why))
            continue
        r = subprocess.run([sys.executable, t], cwd=ROOT, capture_output=True, text=True, timeout=300)
        rel = os.path.relpath(t, ROOT)
        print("%s %s" % ("ok  " if r.returncode == 0 else "FAIL", rel))
        if r.returncode != 0:
            bad.append("$ python3 %s\n%s" % (rel, (r.stdout + r.stderr)[-1200:]))
    if bad:
        print("\n".join(bad))
        return 1
    print("%d agent tests passed" % len(tests))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
