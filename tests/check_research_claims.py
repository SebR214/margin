#!/usr/bin/env python3
"""SEB-423 step 3: the Research claims pass on the real files and fail on a tampered count. The real files are put back afterwards."""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import audit_claims as ac  # noqa: E402

D = os.path.join(HERE, "data", "research")


def swap(name, edit, claim):
    p = os.path.join(D, name)
    old = open(p).read()
    try:
        doc = json.loads(old)
        edit(doc)
        with open(p, "w") as f:
            json.dump(doc, f)
        return claim({})[0]
    finally:
        with open(p, "w") as f:
            f.write(old)


def main():
    fails = []
    for name, claim in (("source_pairs.json", ac.claim_research_pairs), ("capital_controls_months.json", ac.claim_research_months)):
        if not claim({})[0]:
            fails.append(name + " fails on the real files: %s" % (claim({})[1],))
    if swap("source_pairs.json", lambda d: d["bands"].update(tight=d["bands"]["tight"] + 1), ac.claim_research_pairs):
        fails.append("a wrong band count passed")
    if swap("capital_controls_months.json", lambda d: d["months"][0].update(median_premium_pct=d["months"][0]["median_premium_pct"] + 1), ac.claim_research_months):
        fails.append("a wrong month value passed")
    if fails:
        print("FAILED: " + "; ".join(fails))
        return 1
    print("research claims ok: real files pass, tampered numbers fail")
    return 0


if __name__ == "__main__":
    sys.exit(main())
