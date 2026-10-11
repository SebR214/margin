#!/usr/bin/env python3
"""Fail if any code names an Opus or Fable model (SEB-301).

Agents run on Sonnet only. This reads every tracked code file and fails on a
model ID that names the two larger families, so a cost mistake cannot slip in
through a default, a flag or a workflow. Docs, data and the archive are not
scanned: they record history and are not code that calls a model.

    python3 tools/check_models.py            # scan the repo, exit 1 on any hit
    python3 tools/check_models.py --self-test
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = "tools/check_models.py"
CODE = (".py", ".sh", ".js", ".yml", ".yaml", ".service", ".timer", ".toml", ".html")
SKIP_PREFIX = ("data/", "docs/", "node_modules/")
# "claude-opus-5-5", "anthropic/claude-fable-5-1", "opus-4"
BAD = re.compile(r"claude[-/](?:opus|fable)|\b(?:opus|fable)-\d", re.I)


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines()
            if p.endswith(CODE) and p != SELF and not p.startswith(SKIP_PREFIX)]


def scan(paths, read):
    hits = []
    for p in paths:
        try:
            text = read(p)
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = BAD.search(line)
            if m:
                hits.append("%s:%d: %s" % (p, n, m.group(0)))
    return hits


def self_test():
    bad = ["MODEL=claude-opus-5-5", "model: anthropic/claude-fable-5-1", "x = 'opus-4'"]
    good = ["MODEL=claude-sonnet-5", "model: anthropic/claude-sonnet-4.5", "an opus is a work of music"]
    for s in bad:
        assert BAD.search(s), s
    for s in good:
        assert not BAD.search(s), s
    print("check_models self-test: ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    hits = scan(tracked(), lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read())
    if hits:
        print("Opus or Fable model named in code (agents run on Sonnet only):")
        print("\n".join(hits))
        return 1
    print("check_models: no Opus or Fable model in code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
