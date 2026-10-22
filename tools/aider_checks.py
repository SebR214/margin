#!/usr/bin/env python3
"""The offline checks, as one command (SEB-301, track A). No model, no network.

Aider runs this as its test command after every edit (tools/aider_builder.py). It takes the commands of the `checks` job in
.github/workflows/checks.yml, so the builder is judged by the same checks as the PR and the two cannot drift apart. The other
jobs in that file (the full collection run, the rendered page checks) need a browser or the live exchanges and stay in CI.

    python3 tools/aider_checks.py            # run them all, exit 1 and print the tail of each failure
    python3 tools/aider_checks.py --list     # print the commands
    python3 tools/aider_checks.py --self-test
"""
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "checks.yml")
JOB = "checks"


def commands(text, job=JOB):
    """The `run:` command lines of one job, in order. Line based: the file has no anchors or expressions in that job."""
    out, inside, block_indent = [], False, None
    for line in text.split("\n"):
        m = re.match(r"^  ([\w-]+):\s*$", line)
        if m:
            inside = m.group(1) == job
            block_indent = None
            continue
        if not inside:
            continue
        if block_indent is not None:
            ind = len(line) - len(line.lstrip())
            if line.strip() and ind >= block_indent:
                out.append(line.strip())
                continue
            block_indent = None
        m = re.match(r"^(\s+)run:\s*(\|)?\s*(.*)$", line)
        if m:
            if m.group(2):
                block_indent = len(m.group(1)) + 2
            elif m.group(3):
                out.append(m.group(3).strip())
    return [c for c in out if not c.startswith("#")]


def offline(cmds):
    """Only plain python3 and node calls; a pip install, a browser or a shell loop is not run here."""
    keep = []
    for c in cmds:
        try:
            parts = shlex.split(c)
        except ValueError:
            continue
        if parts and parts[0] in ("python3", "node") and not any(ch in c for ch in "$|&;<>`"):
            keep.append(parts)
    return keep


def run(cmds):
    bad = []
    for c in cmds:
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            bad.append("$ %s\n%s" % (" ".join(c), (r.stdout + r.stderr)[-1200:]))
    return bad


def self_test():
    wf = ("jobs:\n  checks:\n    steps:\n      - name: a\n        run: python3 tools/a.py\n"
          "      - name: b\n        run: |\n          python3 b.py --self-test\n          python3 c.py\n"
          "      - name: c\n        run: pip install -r requirements.txt\n"
          "  other:\n    steps:\n      - run: python3 not_this.py\n")
    got = commands(wf)
    assert got == ["python3 tools/a.py", "python3 b.py --self-test", "python3 c.py", "pip install -r requirements.txt"], got
    assert offline(got) == [["python3", "tools/a.py"], ["python3", "b.py", "--self-test"], ["python3", "c.py"]]
    real = offline(commands(open(WORKFLOW).read()))
    assert len(real) > 20 and ["python3", "tools/check_copy.py"] in real, "the real checks job was not read"
    assert not any(c[1] == "tools/aider_checks.py" for c in real), "must not run itself"
    print("aider_checks self-test: ok (%d commands in the checks job)" % len(real))


def main(argv):
    if "--self-test" in argv:
        self_test()
        return 0
    cmds = offline(commands(open(WORKFLOW).read()))
    if len(cmds) < 20:
        print("aider_checks: read only %d commands from checks.yml, something is wrong" % len(cmds))
        return 1
    if "--list" in argv:
        print("\n".join(" ".join(c) for c in cmds))
        return 0
    bad = run(cmds)
    if bad:
        print("%d of %d offline checks failed:\n" % (len(bad), len(cmds)) + "\n\n".join(bad))
        return 1
    print("all %d offline checks passed" % len(cmds))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
