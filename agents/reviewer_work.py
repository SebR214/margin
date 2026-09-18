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

"No review yet" has one deliberate exception (SEB-86). REVIEWER.md's
reader-facing path never calls `gh pr review` at all -- it posts the verdict
on the Linear issue and stops, leaving the PR open for Sebastian. That PR will
never have a GitHub review, so without this exception it reads as needing a
look forever, and the reviewer re-litigates it every pass. If the linked
Linear issue carries a reviewer-stamped comment newer than the head commit,
that counts as the review this PR is short of on GitHub.

Reads GH_TOKEN from the environment like every other gh call, and shells out
to linear.py for the Linear-side check, which reads LINEAR_API_KEY itself.
Stdlib only.
"""

import json
import os
import re
import subprocess
import sys

LINEAR_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linear.py")


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        # A broken check must never be able to stop the machine. Say so on
        # stderr and let the caller decide; the caller runs the pass anyway.
        print("gh %s failed: %s" % (" ".join(args), r.stderr.strip()[:200]),
              file=sys.stderr)
        return None
    return r.stdout


def issue_key(title, branch):
    """The SEB-N key a PR's title or branch name carries, or None.

    Same rule linear.py's stranded-issue filter already uses: builder
    branches start with the lowercased key (BUILDER.md), PR titles carry it
    uppercase.
    """
    blob = (title + " " + branch).upper().replace("_", "-")
    m = re.search(r"\bSEB-\d+\b", blob)
    return m.group(0) if m else None


def last_reviewer_stamp(key):
    """ISO timestamp of the most recent reviewer comment on `key`, or None.

    A failure here (no Linear reachable, no such issue) must not be able to
    hide a PR that genuinely needs review -- return None, same as the gh()
    helper's "could not tell" posture, and the caller falls back to flagging
    it.
    """
    r = subprocess.run(
        [sys.executable, LINEAR_PY, "last-comment", key, "--role", "reviewer"],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("linear.py last-comment %s failed: %s"
              % (key, r.stderr.strip()[:200]), file=sys.stderr)
        return None
    return r.stdout.strip() or None


def main():
    out = gh("pr", "list", "--repo", "SebR214/margin", "--state", "open",
             "--json", "number")
    if out is None:
        return 1
    numbers = [p["number"] for p in json.loads(out or "[]")]

    needs = []
    for n in numbers:
        out = gh("pr", "view", str(n), "--repo", "SebR214/margin",
                 "--json", "reviews,commits,title,headRefName")
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
            key = issue_key(d.get("title", ""), d.get("headRefName", ""))
            stamp = last_reviewer_stamp(key) if key else None
            if stamp and stamp > head:
                continue
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
