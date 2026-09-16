#!/usr/bin/env python3
"""Which open pull requests actually need reviewing.

Prints one PR number per line, or nothing. Exit status is always 0: "no work"
is an answer, not a failure.

The rule is **has the code changed since I last looked**, not "is this
labelled". The previous check asked whether an issue was In Review and not
carrying `needs-sebastian`, which deadlocked three times on 2026-09-16: the
reviewer failed a PR and labelled it, the builder pushed a fix, and the label
stayed -- so the reviewer was blind to the very branch it had asked to be
fixed. Nothing moved until a human cleared the label by hand.

A label describes what a person should do. It cannot tell you whether new code
has arrived, and that is the only question worth asking here.

So: a PR needs review when it has no review yet, or when its head commit is
newer than the newest review on it. Labels do not enter into it -- an issue can
carry `needs-sebastian` and still deserve a fresh pass the moment the builder
pushes a fix, which is exactly the case that kept jamming.

Reads GH_TOKEN from the environment like every other gh call. Stdlib only.
"""

import json
import subprocess
import sys


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        # A broken check must never be able to stop the machine. Say so on
        # stderr and let the caller decide; the caller runs the pass anyway.
        print("gh %s failed: %s" % (" ".join(args), r.stderr.strip()[:200]),
              file=sys.stderr)
        return None
    return r.stdout


def main():
    out = gh("pr", "list", "--repo", "SebR214/margin", "--state", "open",
             "--json", "number")
    if out is None:
        return 1
    numbers = [p["number"] for p in json.loads(out or "[]")]

    needs = []
    for n in numbers:
        out = gh("pr", "view", str(n), "--repo", "SebR214/margin",
                 "--json", "reviews,commits")
        if out is None:
            # Could not tell. Treat as work rather than silently skipping it.
            needs.append(n)
            continue
        d = json.loads(out)
        commits = d.get("commits") or []
        reviews = d.get("reviews") or []
        if not commits:
            continue
        head = max(c["committedDate"] for c in commits)
        if not reviews:
            needs.append(n)
            continue
        last = max(r["submittedAt"] for r in reviews if r.get("submittedAt"))
        if head > last:
            needs.append(n)

    for n in needs:
        print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
