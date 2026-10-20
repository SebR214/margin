#!/usr/bin/env python3
"""Is a collection-code change additive? (SEB-301, Seb's merge rule of 20 Oct.) No model.

    python3 tools/check_additive.py --pr 123 [--repo owner/name]     # from GitHub's file list
    python3 tools/check_additive.py --base origin/main               # from git, against a base
    python3 tools/check_additive.py --self-test

A PR that touches collection code (collector*.py or .github/workflows/collect.yml) merges by itself only if it is additive:
  - new collector files (collector*.py) and new sidecar CSVs are fine;
  - an existing collector*.py is not changed at all;
  - collect.yml may only grow: new lines, or an existing line that keeps its text and gets more appended (a file added to the
    `git add` list); no line deleted or rewritten;
  - no existing CSV is touched, so no existing header changes;
and one full collection run on the branch passes (tools/check_collection_run.py, a separate check). Anything else stays open and
goes in the daily status. A PR that touches no collection code is not judged here.
Exit code: 0 when the PR touches no collection code or is additive, 1 when it is not additive. `--json` prints the verdict.
"""
import json
import os
import re
import subprocess
import sys

COLLECTOR = re.compile(r"^collector[^/]*\.py$")
COLLECT_YML = ".github/workflows/collect.yml"
CSV = re.compile(r"\.csv$")


def touches_collection_code(names):
    return any(COLLECTOR.match(n) or n == COLLECT_YML for n in names)


def yml_append_only(patch):
    """True when a unified diff of collect.yml deletes nothing, or only rewrites a line by appending to it."""
    removed, added = [], []
    for line in (patch or "").split("\n"):
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    toks = lambda s: set(re.findall(r"[\w./-]+\.(?:csv|json|py|md)\b", s))
    seen = set()
    for a_ in added:
        seen |= toks(a_)
    for r in removed:
        if "python3" in r or "run:" in r or "name:" in r:
            return False                 # a step or command is rewritten: not an appended file name
        mine = toks(r)
        if not mine or not mine <= seen:
            return False                 # a line is deleted, or a file name on it disappears
    return True


def classify(files):
    """files: [{filename, status, patch}] with status 'added' | 'modified' | 'removed' | 'renamed'.
    Returns (touches, additive, reasons)."""
    names = [f["filename"] for f in files]
    touches = touches_collection_code(names)
    if not touches:
        return False, True, []
    reasons = []
    for f in files:
        n, st = f["filename"], f["status"]
        if COLLECTOR.match(n) and st != "added":
            reasons.append("%s is an existing collector and is %s" % (n, st))
        elif n == COLLECT_YML:
            if st != "modified" or not yml_append_only(f.get("patch")):
                reasons.append("collect.yml changes more than appended lines")
        elif CSV.search(n) and st != "added":
            reasons.append("%s is an existing CSV and is %s" % (n, st))
        elif st in ("removed", "renamed") and (n.startswith("data/") or COLLECTOR.match(n)):
            reasons.append("%s is %s" % (n, st))
    return True, not reasons, reasons


def from_pr(number, repo):
    out = subprocess.run(["gh", "api", "--paginate", "repos/%s/pulls/%s/files?per_page=100" % (repo, number)],
                         capture_output=True, text=True, check=True).stdout
    # --paginate prints one JSON array per page
    files, dec, i = [], json.JSONDecoder(), 0
    while i < len(out):
        while i < len(out) and out[i].isspace():
            i += 1
        if i >= len(out):
            break
        arr, j = dec.raw_decode(out, i)
        files += arr
        i = j
    return files


def from_git(base):
    names = subprocess.run(["git", "diff", "--name-status", base + "...HEAD"], capture_output=True, text=True, check=True).stdout.split("\n")
    files = []
    for line in names:
        if not line.strip():
            continue
        parts = line.split("\t")
        st = {"A": "added", "M": "modified", "D": "removed"}.get(parts[0][0], "renamed")
        name = parts[-1]
        patch = subprocess.run(["git", "diff", base + "...HEAD", "--", name], capture_output=True, text=True).stdout
        files.append({"filename": name, "status": st, "patch": patch})
    return files


def self_test():
    new = lambda n: {"filename": n, "status": "added", "patch": ""}
    mod = lambda n, p="": {"filename": n, "status": "modified", "patch": p}
    assert classify([mod("js/home.js")]) == (False, True, [])
    t, ok, why = classify([new("collector_depth.py"), new("data/depth.csv"), new("tools/check_depth.py")])
    assert t and ok and not why
    t, ok, why = classify([mod("collector_p2p.py")])
    assert t and not ok and "existing collector" in why[0]
    t, ok, why = classify([mod("data/p2p_basis.csv"), new("collector_x.py")])
    assert t and not ok and "existing CSV" in why[0]
    grow = "@@ -10,3 +10,4 @@\n   run: python3 a.py\n+      - name: Collect depth\n+        run: python3 collector_depth.py\n"
    assert classify([new("collector_depth.py"), mod(COLLECT_YML, grow)])[1]
    append = "@@ -630,2 +630,2 @@\n-                   data/sources_daily.json data/findings.json \\\n+                   data/sources_daily.json data/findings.json data/depth.csv \\\n"
    assert classify([new("collector_depth.py"), mod(COLLECT_YML, append)])[1], "appending a file to the git add list is additive"
    rewrite = "@@ -630,2 +630,2 @@\n-        run: python3 collector_p2p.py\n+        run: python3 collector_p2p.py --fast\n"
    assert not classify([mod(COLLECT_YML, rewrite)])[1], "adding an argument to an existing command is not additive"
    rewrite2 = "@@ -1,2 +1,2 @@\n-        run: python3 collector_basis.py\n+        run: python3 collector_other.py\n"
    assert not classify([mod(COLLECT_YML, rewrite2)])[1], "replacing a line is not additive"
    gone = "@@ -1,2 +1,1 @@\n-        run: python3 collector_basis.py\n"
    assert not classify([mod(COLLECT_YML, gone)])[1], "deleting a line is not additive"
    assert not classify([{"filename": "collector_p2p.py", "status": "removed", "patch": ""}])[1]
    print("check_additive self-test: ok")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--pr" in argv:
        repo = argv[argv.index("--repo") + 1] if "--repo" in argv else os.environ.get("GITHUB_REPOSITORY", "SebR214/margin")
        files = from_pr(argv[argv.index("--pr") + 1], repo)
    elif "--base" in argv:
        files = from_git(argv[argv.index("--base") + 1])
    else:
        sys.exit(__doc__)
    touches, ok, why = classify(files)
    if "--json" in argv:
        print(json.dumps({"touches_collection_code": touches, "additive": ok, "reasons": why}))
    elif not touches:
        print("no collection code touched")
    elif ok:
        print("additive: new collector files or sidecar CSVs only, collect.yml only grows")
    else:
        print("NOT ADDITIVE:\n- " + "\n- ".join(why))
    return 0 if (ok or not touches) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
