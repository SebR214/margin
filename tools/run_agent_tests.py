#!/usr/bin/env python3
"""Run every test an agent job added: tests/agent_*.py (SEB-301, 25 Oct). No model, no network.

Each researcher job lists one new test file, tests/agent_<name>.py, and its `done when:` names it. This one step in checks.yml runs all of
them, so a new test is part of CI and of the Aider builder's test command (tools/aider_checks.py) without editing checks.yml.

    python3 tools/run_agent_tests.py
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    tests = sorted(glob.glob(os.path.join(ROOT, "tests", "agent_*.py")))
    bad = []
    for t in tests:
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
    sys.exit(main())
