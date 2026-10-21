#!/usr/bin/env python3
"""Is a collection-code change additive? (SEB-301, Seb's merge rule of 20 Oct.) No model.

    python3 tools/check_additive.py --compare main --sha <sha> [--repo owner/name]   # from the diff of one exact commit (what automerge uses)
    python3 tools/check_additive.py --pr 123 [--repo owner/name]     # from GitHub's file list (can lag right after a push)
    python3 tools/check_additive.py --base origin/main               # from git, against a base
    python3 tools/check_additive.py --self-test

A PR that touches collection code (collector*.py or .github/workflows/collect.yml) merges by itself only if it is additive:
  - new collector files (collector*.py) and new sidecar CSVs are fine;
  - an existing collector*.py is not changed at all, except (SEB-301, 21 Oct) to add whole new entries to a table it already has
    that is keyed by route, like `"USD->PHP": {...},` in collector.py's CORRIDORS or collector_providers.py's CORRIDOR_CCY:
    no line removed or rewritten, the added lines are complete entries of literals at the table's top level, and no key repeats;
  - collect.yml may only grow: new lines, or an existing line that keeps its text and gets more appended (a file added to the
    `git add` list); no line deleted or rewritten;
  - no existing CSV is touched, so no existing header changes;
and one full collection run on the branch passes (tools/check_collection_run.py, a separate check). Anything else stays open and
goes in the daily status. A PR that touches no collection code is not judged here.
Exit code: 0 when the PR touches no collection code or is additive, 1 when it is not additive. `--json` prints the verdict.
"""
import ast
import json
import os
import re
import subprocess
import sys

COLLECTOR = re.compile(r"^collector[^/]*\.py$")
COLLECT_YML = ".github/workflows/collect.yml"
CSV = re.compile(r"\.csv$")
ROUTE_KEY = re.compile(r"^[A-Z]{3}->[A-Z]{3}$")


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


def table_entries_only(patch, new_text):
    """True when a diff of an existing collector only adds whole entries to route-keyed tables it already has. `new_text` is the
    file after the change: each run of added lines must sit strictly inside one module-level dict literal, parse on its own as
    dict entries of literals whose keys are routes ("USD->PHP"), start at that dict's top level (4 spaces), and leave no key twice."""
    if not patch or not new_text:
        return False
    try:
        tree = ast.parse(new_text)
    except SyntaxError:
        return False
    tables = [(n.value.lineno, n.value.end_lineno, n.value) for n in tree.body
              if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Dict)]
    runs, cur, at = [], None, None
    for line in patch.split("\n"):
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if m:
            at, cur = int(m.group(1)), None
            continue
        if at is None or line.startswith("\\"):
            continue                      # file headers before the first hunk, "\ No newline at end of file"
        if line.startswith("-"):
            return False                  # a line removed or rewritten
        if line.startswith("+"):
            if cur is None:
                cur = [at, []]
                runs.append(cur)
            cur[1].append(line[1:])
        else:
            cur = None
        at += 1
    if not runs:
        return False
    for start, added in runs:
        end = start + len(added) - 1
        host = [d for a, b, d in tables if a < start and end < b]
        if len(host) != 1:
            return False                  # not inside one existing table (or it is the table's own first or last line)
        code = [l for l in added if l.strip() and not l.strip().startswith("#")]
        if not code:
            continue                      # a comment inside a table
        if not re.match(r"^ {4}\S", code[0]):
            return False                  # not at the table's top level
        try:
            entries = ast.literal_eval("{\n" + "\n".join(added) + "\n}")
        except (ValueError, SyntaxError):
            return False
        if not entries or not all(isinstance(k, str) and ROUTE_KEY.match(k) for k in entries):
            return False
        keys = [k.value for k in host[0].keys if isinstance(k, ast.Constant)]
        if len(keys) != len(set(keys)) or len(keys) != len(host[0].keys):
            return False                  # a key twice would quietly replace an existing route's entry
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
        if COLLECTOR.match(n) and st == "modified" and table_entries_only(f.get("patch"), f.get("content")):
            continue                      # new route entries in a table it already has (SEB-301, 21 Oct)
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


def from_compare(base, sha, repo):
    """The files changed between `base` and the exact commit `sha`. Computed for that commit, so it cannot lag behind a push the way a PR's
    own file list can (that lag let a collector edit through once, 20 Oct)."""
    out = subprocess.run(["gh", "api", "repos/%s/compare/%s...%s" % (repo, base, sha)], capture_output=True, text=True, check=True).stdout
    doc = json.loads(out)
    if doc.get("total_commits", 0) and not doc.get("files"):
        raise SystemExit("GitHub returned no file list for %s...%s" % (base, sha))
    files = doc.get("files") or []
    for f in files:
        if COLLECTOR.match(f["filename"]) and f.get("status") == "modified":
            f["content"] = file_at(repo, f["filename"], sha)
    return files


def file_at(repo, path, ref):
    """The file as it is at `ref`, or None (then the table rule cannot pass: fail closed)."""
    r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw", "repos/%s/contents/%s?ref=%s" % (repo, path, ref)],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


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
        f = {"filename": name, "status": st, "patch": patch}
        if COLLECTOR.match(name) and st == "modified":
            r = subprocess.run(["git", "show", "HEAD:" + name], capture_output=True, text=True)
            f["content"] = r.stdout if r.returncode == 0 else None
        files.append(f)
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
    # SEB-301, 21 Oct: a new route entry in an existing route table is additive
    old = 'X = 1\nCORRIDORS = {\n    "SGD->PHP": {\n        "src": "SGD",\n    },\n}\nCCY = {\n    "SGD->PHP": ("SGD", "PHP"),\n}\n\ndef f():\n    return 1\n'
    entry = '    "USD->PHP": {\n        # fees copied from USD->MXN\n        "src": "USD",\n    },'
    new_text = old.replace('    },\n}\nCCY', '    },\n' + entry + '\n}\nCCY').replace('("SGD", "PHP"),\n}', '("SGD", "PHP"),\n    "USD->PHP": ("USD", "PHP"),\n}')
    p1 = "@@ -4,3 +4,7 @@\n         \"src\": \"SGD\",\n     },\n" + "".join("+" + l + "\n" for l in entry.split("\n")) + " }\n"
    p2 = "@@ -8,2 +12,3 @@\n     \"SGD->PHP\": (\"SGD\", \"PHP\"),\n+    \"USD->PHP\": (\"USD\", \"PHP\"),\n }\n"
    assert table_entries_only(p1 + p2, new_text), "a new route in each table"
    assert classify([mod("collector.py", p1 + p2) | {"content": new_text}, mod(COLLECT_YML, grow)])[1]
    assert not classify([mod("collector.py", p1)])[1], "no file content: fail closed"
    dup = new_text.replace('"USD->PHP": {', '"SGD->PHP": {')
    assert not table_entries_only(p1.replace("USD->PHP", "SGD->PHP") + p2, dup), "the same key twice replaces a route: not additive"
    inner = old.replace('        "src": "SGD",\n', '        "src": "SGD",\n        "USD->PHP": 1,\n')
    assert not table_entries_only('@@ -4,2 +4,3 @@\n         "src": "SGD",\n+        "USD->PHP": 1,\n     },\n', inner), "inside an entry"
    code = old.replace("    return 1\n", "    return 1\n    \"USD->PHP\": 2,\n")
    assert not table_entries_only('@@ -11,1 +11,2 @@\n     return 1\n+    "USD->PHP": 2,\n', code), "outside any table"
    notroute = new_text.replace('    "USD->PHP": ("USD", "PHP"),', '    "timeout": 99,')
    assert not table_entries_only(p2.replace('\\"USD->PHP\\": (\\"USD\\", \\"PHP\\")', '"timeout": 99').replace('+    "USD->PHP": ("USD", "PHP"),', '+    "timeout": 99,'), notroute), "a key that is not a route"
    edit = "@@ -4,1 +4,1 @@\n-        \"src\": \"SGD\",\n+        \"src\": \"SGX\",\n"
    assert not table_entries_only(edit, old.replace('"SGD",\n    }', '"SGX",\n    }')), "a rewritten line"
    print("check_additive self-test: ok")


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--compare" in argv:
        repo = argv[argv.index("--repo") + 1] if "--repo" in argv else os.environ.get("GITHUB_REPOSITORY", "SebR214/margin")
        files = from_compare(argv[argv.index("--compare") + 1], argv[argv.index("--sha") + 1], repo)
    elif "--pr" in argv:
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
    if "--json" in argv:
        return 0                    # the verdict is in the JSON; the caller decides (automerge reads it and fails closed)
    return 0 if (ok or not touches) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
