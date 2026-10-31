#!/usr/bin/env python3
"""SEB-423 step 1: the home facts are built from the files, and the claims audit catches a fact that does not match its source.

Builds data/home_facts.json in memory, checks the shape, then writes a tampered copy and checks that tools/audit_claims.py fails it.
The real file is put back afterwards. Run: python3 tests/check_home_facts.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import audit_claims as ac  # noqa: E402
import emit_home_facts as ehf  # noqa: E402

PATH = os.path.join(HERE, "data", "home_facts.json")


def main():
    doc = ehf.build()
    fails = []
    items = doc["what_changed"]
    if len(items) > 8 or [i["date"] for i in items] != sorted((i["date"] for i in items), reverse=True):
        fails.append("what_changed is not newest first, at most 8")
    old = open(PATH).read() if os.path.exists(PATH) else None
    try:
        with open(PATH, "w") as f:
            json.dump(doc, f)
        ok, v = ac.claim_home_what_changed({})
        if not ok:
            fails.append("a fresh fact file failed the audit: %s" % (v,))
        ok, v = ac.claim_home_largest_move({})
        if not ok:
            fails.append("a fresh largest move failed the audit: %s" % (v,))
        if items:
            bad = json.loads(json.dumps(doc))
            it = bad["what_changed"][0]
            if "pct" in it:
                it["pct"] = it["pct"] + 3
            elif "status" in it:
                it["status"] = "nonsense"
            else:
                it["date"] = "2000-01-01"
            with open(PATH, "w") as f:
                json.dump(bad, f)
            ok, v = ac.claim_home_what_changed({})
            if ok:
                fails.append("a tampered what-changed line passed the audit")
        fake = json.loads(json.dumps(doc))
        fake["largest_move"] = {"ccy": "AED", "country": "United Arab Emirates", "points": 99.9, "direction": "dearer", "since": "2020-01-01"}
        with open(PATH, "w") as f:
            json.dump(fake, f)
        ok, v = ac.claim_home_largest_move({})
        if ok:
            fails.append("an invented largest move passed the audit")
    finally:
        if old is None:
            os.remove(PATH)
        else:
            with open(PATH, "w") as f:
                f.write(old)
    if fails:
        print("FAILED: " + "; ".join(fails))
        return 1
    print("home facts ok: %d lines, fresh facts pass the audit, tampered ones fail" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
