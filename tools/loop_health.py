#!/usr/bin/env python3
"""What the loops cost and whether they are earning it.

The product role's bug triggers all measure the DATA -- delivery, stale sources,
withheld counts, unexplained moves. None of them measured the machine, so the
machine's own waste was invisible to it. Over 2026-09-16/17 the builder woke a
model 2,420 times and 2,300 of those ran under sixty seconds: a model booting up
to conclude there was nothing to do. Nobody filed it, because nobody was looking,
because nothing told them to look.

This prints the numbers so the product role can look without a model doing
arithmetic on log files. Stdlib only, no model call, safe to run every pass.

    python3 tools/loop_health.py              # today
    python3 tools/loop_health.py 2026-09-16   # a given day
"""

import collections
import datetime
import io
import json
import os
import sys

LOGDIR = "/var/log/margin"
IDLE_SECONDS = 45          # run.sh's own threshold for "this pass did nothing"
WASTE_ALARM = 0.60         # 60% of wakes idle is worth filing
THRASH_ALARM = 20          # identical consecutive no-op passes


def rows(role, day):
    path = os.path.join(LOGDIR, "%s.jsonl" % role)
    out = []
    try:
        for line in io.open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("finished_utc", "").startswith(day):
                out.append(d)
    except OSError:
        pass
    return out


def _idle(r):
    """A pass counts as idle if it was fast (booted, found nothing, exited) OR
    if agents/run.sh's own before/after signature compare says the
    buildable/reviewable world it looked at didn't move -- SEB-93: 24 passes
    on SEB-59 ran 61-131s each, all of them well past IDLE_SECONDS, because
    each one did a fresh, real re-check that landed on the same unchanged
    conclusion. Wall-clock alone called every one of those "not idle"; the
    signature flag, recorded by run.sh since SEB-93, catches what the clock
    can't.
    """
    return (r.get("seconds") or 0) < IDLE_SECONDS or bool(r.get("sig_idle"))


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else \
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    print("loop health for %s" % day)
    findings = []

    for role in ("builder", "reviewer", "product"):
        rs = rows(role, day)
        if not rs:
            print("  %-9s no passes recorded" % role)
            continue
        wakes = [r for r in rs if (r.get("seconds") or 0) > 0]
        idle = [r for r in wakes if _idle(r)]
        reasons = collections.Counter(r.get("reason", "?") for r in rs)
        share = (len(idle) / len(wakes)) if wakes else 0.0
        print("  %-9s passes %-5d model wakes %-5d  woke-and-found-nothing %-5d (%.0f%%)"
              % (role, len(rs), len(wakes), len(idle), share * 100))
        top = ", ".join("%s x%d" % (k, v) for k, v in reasons.most_common(3))
        print("            reasons: %s" % top)

        # A model woken to discover there is nothing to do is the guard failing
        # at its one job.
        if wakes and share >= WASTE_ALARM and len(idle) >= 20:
            findings.append(
                "%s woke a model %d times and %d of those (%.0f%%) ran under %ds -- "
                "the guard in agents/run.sh is letting the model answer a question "
                "a script should answer. File it."
                % (role, len(wakes), len(idle), share * 100, IDLE_SECONDS))

        # The same no-op repeating is a loop with something true to say and
        # nowhere to record it. That was SEB-71.
        streak = 0
        worst = 0
        for r in rs:
            if (r.get("seconds") or 0) > 0 and _idle(r):
                streak += 1
                worst = max(worst, streak)
            else:
                streak = 0
        if worst >= THRASH_ALARM:
            findings.append(
                "%s ran %d no-op model passes in a row -- it is repeating itself "
                "because it has something true to say and nowhere to put it. "
                "See SEB-71 for the shape of this." % (role, worst))

    print()
    if findings:
        print("FILE THESE:")
        for f in findings:
            print("  - %s" % f)
    else:
        print("nothing to file: no loop is wasting model calls today")
    return 0


if __name__ == "__main__":
    sys.exit(main())
