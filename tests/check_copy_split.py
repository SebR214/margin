#!/usr/bin/env python3
"""The copy split holds: copy.json is the merge of copy/*.json, the merge is
deterministic, and two branches that edit different pages merge without a
conflict (the reason copy.json was split).

Offline and stdlib-only. Run: python3 tests/check_copy_split.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import build_copy  # noqa: E402

fails = []


def chk(name, cond):
    if not cond:
        fails.append(name)


# 1. copy.json is exactly what the merge of copy/ gives, and the merge is repeatable.
merged = build_copy.dump(build_copy.merge(build_copy.load()))
chk("merge is deterministic", merged == build_copy.dump(build_copy.merge(build_copy.load())))
chk("copy.json is the merge of copy/", json.load(open(os.path.join(HERE, "copy.json"), encoding="utf-8")) == json.loads(merged))
chk("top-level order follows ORDER", list(json.loads(merged))[:len(build_copy.ORDER)] == [k for k in build_copy.ORDER if k in json.loads(merged)])
try:
    build_copy.merge({"a.json": {"k": 1}, "b.json": {"k": 2}})
    chk("a key in two files is refused", False)
except SystemExit:
    pass

# 2. Two branches, two pages, one merge, no conflict.
tmp = tempfile.mkdtemp()


def git(*a, cwd=tmp):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def write(path, doc):
    os.makedirs(os.path.dirname(os.path.join(tmp, path)), exist_ok=True)
    with open(os.path.join(tmp, path), "w", encoding="utf-8") as f:
        f.write(build_copy.dump(doc))


try:
    git("init", "-q", "-b", "main")
    pages = {"copy/home.json": {"home": {"headline": "a"}}, "copy/tape.json": {"tape": {"title": "b"}}}
    for p, d in pages.items():
        write(p, d)
    write("copy.json", {"home": {"headline": "a"}, "tape": {"title": "b"}})
    git("add", "-A")
    git("commit", "-qm", "base")
    for br, p, d in (("pr-home", "copy/home.json", {"home": {"headline": "a2"}}),
                     ("pr-tape", "copy/tape.json", {"tape": {"title": "b2"}})):
        git("checkout", "-q", "-b", br, "main")
        write(p, d)
        git("commit", "-qam", br)
    git("checkout", "-q", "main")
    rc1, _ = git("merge", "-q", "--no-edit", "pr-home")
    rc2, out2 = git("merge", "-q", "--no-edit", "pr-tape")
    chk("two PRs on different pages merge cleanly", rc1 == 0 and rc2 == 0)
    got = {}
    for n in ("home", "tape"):
        got.update(json.load(open(os.path.join(tmp, "copy", n + ".json"))))
    chk("both edits survive the merge", got == {"home": {"headline": "a2"}, "tape": {"title": "b2"}})
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    print("COPY SPLIT FAILED: " + ", ".join(fails))
    sys.exit(1)
print("copy split ok: copy.json is the merge of copy/*.json, and edits to different pages merge cleanly")
