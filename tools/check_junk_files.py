"""Fail if a tracked file looks like an iCloud duplicate ("name 2.ext").

Those copies of workflows kept running next to the real ones and merged a PR
that the real automerge had left open (#578, 20 Oct).
"""
import re
import subprocess
import sys

JUNK = re.compile(r" \d+(\.[A-Za-z0-9]+)?$")


def junk(paths):
    return [p for p in paths if JUNK.search(p)]


def main():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    bad = junk(out.splitlines())
    if bad:
        print("duplicate files tracked (name N.ext):")
        for p in bad:
            print("  " + p)
        return 1
    print("no duplicate files tracked")
    return 0


def self_test():
    assert junk(["a/b 2.yml", "c 10", "ok.py", "data/x.csv"]) == ["a/b 2.yml", "c 10"]
    print("self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    sys.exit(main())
