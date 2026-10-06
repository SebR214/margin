#!/usr/bin/env python3
"""CI gate: reader-facing words live in copy/*.json and only the writer agent changes them.

The words are one file per page, copy/<page>.json. copy.json (what the pages
fetch) is generated from them by tools/build_copy.py, so this gate reads the
merged result of copy/*.json, on the base and on the PR, and compares words,
not files. A base that predates copy/ is read from its copy.json.

Builder, reviewer and page agents bind numbers to fields and build features.
They do not change words. This check fails a pull request that

  1. changes the copy deck (other than adding a new key whose value is the empty
     string: the slot a feature needs, shipped empty, which the page must not
     render until the writer fills it), or
  2. adds literal reader-facing text to an html or js file (a text node, an
     attribute such as placeholder or aria-label, or a string literal that
     reads as prose, compared with the same file on the base branch).

The one exception is a WRITER pull request: head branch `writer/<anything>`.
It may change copy/*.json (and the generated copy.json) and nothing else, its description must carry the
rendered text of the page under a "## Rendered text" heading, and it passes
only after the owner has approved it: the label `copy-approved` added by the
owner's own account after the last push. No other gate changes that.

Usage:
  python3 tools/check_copy_lock.py --base origin/main            # CI
  python3 tools/check_copy_lock.py --self-test
Environment in CI: GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, PR_HEAD_REF,
PR_AUTHOR, LOCK_ROOT (the checkout; CI runs this file from the BASE branch so a
PR cannot weaken the check that judges it), OWNER_LOGIN (default SebR214). Without PR_NUMBER the writer approval step is
skipped (local run).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser

HERE = os.environ.get("LOCK_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER = os.environ.get("OWNER_LOGIN", "SebR214")
# The lock itself and the writer's brief change only in a PR the owner opened.
PROTECTED = ("tools/check_copy_lock.py", ".github/workflows/checks.yml", "agents/WRITER.md")
SKIP_PREFIXES = ("docs/", "tests/", ".claude/", ".debate/", "data/", "agents/", "tools/", ".github/")
ATTRS = ("placeholder", "aria-label", "title", "alt", "label", "value")
SKIP_TAGS = ("script", "style", "template", "noscript", "code", "svg")


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def words(s):
    return [w for w in re.split(r"\s+", s.strip()) if re.match(r"^[“\"(]?[A-Za-z’'\-]{2,}[,.!?;:%”\")]*$", w)]


def is_prose(s):
    """Two or more real words and nothing that reads as code, CSS, a path or markup."""
    s = s.strip()
    if len(words(s)) < 2:
        return False
    if re.search(r"[{}\[\]=<>/\\_#()@|]", s):
        return False
    if re.search(r"https?:|\.(js|css|json|png|svg|html|csv)\b", s):
        return False
    return all(re.match(r"^[A-Za-z0-9’'\-,.!?%&;:+$£€\"“”…→—–*]+$", w) for w in s.split())


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.scripts, self.stack, self._buf = [], [], [], None

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        for k, v in attrs:
            if k in ATTRS and v and is_prose(v):
                self.out.append(v)
        if tag in ("script", "style"):
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "script" and self._buf is not None:
            self.scripts.append("".join(self._buf))
        if tag in ("script", "style"):
            self._buf = None
        while self.stack:
            if self.stack.pop() == tag:
                break

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)
            return
        if any(t in SKIP_TAGS for t in self.stack):
            return
        t = re.sub(r"\s+", " ", data).strip()
        if t and len(words(t)) >= 2:
            self.out.append(t)


def _js_strings(src):
    """String literals from JS source, skipping comments."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"`":
            q, j, buf = c, i + 1, []
            while j < n and src[j] != q:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1] if src[j + 1] not in "nrt" else " ")
                    j += 2
                    continue
                if src[j] == "\n" and q != "`":
                    break
                buf.append(src[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
        else:
            i += 1
    return out


def reader_text(path, content):
    """Set of normalised reader-facing text items in a file."""
    items = set()
    scripts = []
    if path.endswith(".html"):
        # tools/bake_homepage.py writes data-generated fallback text between BAKE markers: not authored words.
        content = re.sub(r"<!--BAKE:START[^>]*-->.*?<!--BAKE:END[^>]*-->", " ", content, flags=re.S)
        p = _Text()
        try:
            p.feed(content)
        except Exception:  # noqa: BLE001
            pass
        items.update(norm(t) for t in p.out)
        scripts = p.scripts
    elif path.endswith(".js"):
        scripts = [content]
    for js in scripts:
        for s in _js_strings(js):
            if "<" in s and ">" in s:  # an html fragment built in script
                p = _Text()
                try:
                    p.feed(s)
                except Exception:  # noqa: BLE001
                    pass
                items.update(norm(t) for t in p.out)
            elif is_prose(s):
                items.add(norm(s))
    return {i for i in items if i}


def git(*args):
    r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
    return r.returncode, r.stdout


def show(base, path):
    rc, out = git("show", "%s:%s" % (base, path))
    return out if rc == 0 else ""


def changed_files(base):
    for spec in (base + "...HEAD", base):
        rc, out = git("diff", "--name-only", spec)
        if rc == 0:
            return [l.strip() for l in out.splitlines() if l.strip()]
    return []


def flatten(o, prefix=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flatten(v, prefix + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flatten(v, prefix + "[%d]" % i)
    else:
        yield prefix, o


def is_copy(f):
    return f == "copy.json" or (f.startswith("copy/") and f.endswith(".json"))


def merge_parts(parts):
    """Merge per-page copy files (a list of JSON texts) into one JSON text. Order is irrelevant here:
    words are compared, not bytes."""
    merged = {}
    for t in parts:
        doc = json.loads(t)
        for k in doc:
            if k in merged:
                raise ValueError("top-level key %r is in two copy files" % k)
        merged.update(doc)
    return json.dumps(merged)


def copy_at(ref):
    """The merged copy deck as JSON text: at git ref REF, or in the working tree when REF is None.
    Reads copy/*.json; falls back to copy.json where copy/ does not exist (a base before the split)."""
    try:
        if ref is None:
            d = os.path.join(HERE, "copy")
            names = sorted(n for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []
            parts = [open(os.path.join(d, n), encoding="utf-8").read() for n in names]
            fallback = lambda: open(os.path.join(HERE, "copy.json"), encoding="utf-8").read()
        else:
            rc, out = git("ls-tree", "--name-only", ref, "copy/")
            names = sorted(l.strip() for l in out.splitlines() if l.strip().endswith(".json")) if rc == 0 else []
            parts = [show(ref, n) for n in names]
            fallback = lambda: show(ref, "copy.json")
        return merge_parts(parts) if parts else fallback()
    except (OSError, ValueError) as e:
        return "invalid: %s" % e


def copy_violations(old_text, new_text):
    """Changes to the copy deck that are not an empty new slot."""
    try:
        old = dict(flatten(json.loads(old_text))) if old_text.strip() else {}
        new = dict(flatten(json.loads(new_text)))
    except ValueError as e:
        return ["the copy deck is not valid JSON: %s" % e]
    bad = []
    for k, v in old.items():
        if k not in new:
            bad.append("removed %s" % k)
        elif new[k] != v:
            bad.append("changed %s" % k)
    for k, v in new.items():
        if k not in old and v not in ("", None):
            bad.append("added %s with words in it (new slots ship empty)" % k)
    return bad


def added_prose(base, files):
    bad = []
    for f in files:
        if f.startswith(SKIP_PREFIXES) or not (f.endswith(".html") or f.endswith(".js")):
            continue
        if re.search(r" \d\.", f):  # iCloud duplicate scratch copies
            continue
        path = os.path.join(HERE, f)
        if not os.path.exists(path):
            continue
        new = reader_text(f, open(path, encoding="utf-8", errors="replace").read())
        old = reader_text(f, show(base, f))
        for t in sorted(new - old):
            bad.append("%s: %s" % (f, t[:90]))
    return bad


def api(path):
    req = urllib.request.Request("https://api.github.com/repos/%s%s" % (os.environ["GITHUB_REPOSITORY"], path),
                                 headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                                          "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def writer_approved():
    """(ok, why). The owner's own account added `copy-approved` after the last push."""
    n = os.environ["PR_NUMBER"]
    pr = api("/pulls/%s" % n)
    body = pr.get("body") or ""
    m = re.search(r"##\s*Rendered text\s*\n(.+)", body, re.S | re.I)
    if not m or len(words(m.group(1))) < 20:
        return False, "the PR description needs a '## Rendered text' section with the page text as it renders"
    ok, why = owner_label()
    return ok, why


def copy_text_equal(old_text, new_text):
    """Copy deck content, ignoring formatting: same keys, same values."""
    try:
        return json.loads(old_text or "{}") == json.loads(new_text or "{}")
    except ValueError:
        return old_text == new_text


def commit_before(commits, when):
    """The last of COMMITS (GitHub API order: oldest first) committed at or before WHEN."""
    before = [c for c in commits if c["commit"]["committer"]["date"] <= when]
    return before[-1]["sha"] if before else None


def owner_label():
    """(ok, why): the owner's own account approved the copy deck's current words.

    The usual case is the label was added after the last push. But approval
    follows the words, not the commit: a push after the label that left
    the deck's words exactly as they were when approved (a merge from main, a
    layout or js-only commit) does not need re-approval. Only a push that
    actually changes the approved text does."""
    n = os.environ["PR_NUMBER"]
    pr = api("/pulls/%s" % n)
    head_date = api("/commits/%s" % pr["head"]["sha"])["commit"]["committer"]["date"]
    ev = [e for e in api("/issues/%s/events?per_page=100" % n)
          if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == "copy-approved"]
    ev = [e for e in ev if (e.get("actor") or {}).get("login") == OWNER]
    if not ev:
        return False, ("waiting for %s to approve: the label 'copy-approved', added by their own account after the "
                       "last push" % OWNER)
    latest = max(ev, key=lambda e: e["created_at"])
    if latest["created_at"] >= head_date:
        return True, "approved by %s" % OWNER
    commits = api("/pulls/%s/commits?per_page=100" % n)
    approved_sha = commit_before(commits, latest["created_at"])
    if approved_sha is None:
        return False, ("waiting for %s to approve: the label 'copy-approved', added by their own account after the "
                       "last push" % OWNER)
    approved_copy = copy_at(approved_sha)
    current_copy = copy_at(None)
    if copy_text_equal(approved_copy, current_copy):
        return True, "approved by %s (words unchanged since approval; a later push touched other files)" % OWNER
    return False, ("waiting for %s to re-approve: the copy words changed since the 'copy-approved' label was "
                   "added" % OWNER)


def run(base):
    files = changed_files(base)
    head_ref = os.environ.get("PR_HEAD_REF", "")
    problems = []
    is_writer = head_ref.startswith("writer/")
    author = os.environ.get("PR_AUTHOR")
    if author is not None and author != OWNER:
        for f in files:
            if f in PROTECTED:
                problems.append("%s changes only in a PR opened by %s" % (f, OWNER))
    if is_writer:
        extra = [f for f in files if not is_copy(f)]
        if extra:
            problems.append("a writer PR may change copy/*.json only, it also changes: " + ", ".join(extra[:6]))
        if any(is_copy(f) for f in files) and not os.environ.get("PR_NUMBER"):
            print("copy lock: writer PR, approval step skipped (no PR_NUMBER)")
        elif any(is_copy(f) for f in files):
            ok, why = writer_approved()
            if not ok:
                problems.append(why)
            else:
                print("copy lock: writer PR " + why)
    else:
        if any(is_copy(f) for f in files):
            for v in copy_violations(copy_at(base), copy_at(None)):
                problems.append("copy: " + v)
        if "copy.json" in files and os.path.isdir(os.path.join(HERE, "copy")):
            try:
                same = json.loads(open(os.path.join(HERE, "copy.json"), encoding="utf-8").read()) == json.loads(copy_at(None))
            except (OSError, ValueError):
                same = False
            if not same:
                problems.append("copy.json is generated from copy/*.json: edit copy/<page>.json and run tools/build_copy.py")
        problems += ["literal text added to " + b for b in added_prose(base, files)]
    if problems and not is_writer and os.environ.get("PR_NUMBER") and not any("only in a PR opened by" in p for p in problems):
        ok, why = owner_label()  # the owner can approve any copy change, e.g. a revert, the same way
        if ok:
            print("copy lock: words changed outside a writer PR, " + why)
            return 0
    if problems:
        print("COPY LOCK FAILED. Words belong to the writer agent, not to this PR.")
        for p in problems[:40]:
            print("  - " + p)
        print("Bind numbers to fields and build the feature. If it needs new words, ship the slot in copy/<page>.json "
              "with an empty value and make the page not render it until the writer fills it.")
        return 1
    print("copy lock ok: no reader-facing words changed outside a writer PR")
    return 0


def self_test():
    fails = []

    def chk(name, cond):
        if not cond:
            fails.append(name)

    html_old = '<h1>Hello there</h1><script>var a = "x";</script>'
    html_new = ('<h1>Hello there</h1><p>A brand new sentence</p><input placeholder="Search a country">'
                '<script>var a = "x"; el.textContent = "Typed words in script"; '
                'h += \'<div class="p">Words in html string</div>\'; var u="data/x.json"; var s="font-size: 14px";</script>')
    added = reader_text("p.html", html_new) - reader_text("p.html", html_old)
    chk("text node", "a brand new sentence" in added)
    chk("placeholder", "search a country" in added)
    chk("script string", "typed words in script" in added)
    chk("html in script", "words in html string" in added)
    chk("path ignored", not any("data/x.json" in a for a in added))
    chk("css ignored", not any("font-size" in a for a in added))
    chk("unchanged ignored", "hello there" not in added)
    js = 'var q = "section .small"; x = "Show more results"; // a comment with words'
    chk("js prose", "show more results" in reader_text("a.js", js))
    chk("js comment skipped", "a comment with words" not in reader_text("a.js", js))
    chk("js selector", "section .small" not in reader_text("a.js", js))
    old = json.dumps({"a": {"x": "words here"}})
    chk("copy edit", copy_violations(old, json.dumps({"a": {"x": "other words"}})))
    chk("copy new words", copy_violations(old, json.dumps({"a": {"x": "words here", "y": "new words"}})))
    chk("copy empty slot ok", not copy_violations(old, json.dumps({"a": {"x": "words here", "y": ""}})))
    chk("copy remove", copy_violations(old, json.dumps({"a": {}})))
    chk("merge parts", json.loads(merge_parts(['{"a": 1}', '{"b": 2}'])) == {"a": 1, "b": 2})
    try:
        merge_parts(['{"a": 1}', '{"a": 2}'])
        chk("merge duplicate key refused", False)
    except ValueError:
        pass
    chk("copy files recognised", is_copy("copy/home.json") and is_copy("copy.json") and not is_copy("tools/x.json"))
    chk("approval text equal, reformatted", copy_text_equal('{"a": "x"}', '{\n  "a": "x"\n}'))
    chk("approval text differs", not copy_text_equal('{"a": "x"}', '{"a": "y"}'))
    commits = [{"sha": "c1", "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}}},
               {"sha": "c2", "commit": {"committer": {"date": "2026-01-02T00:00:00Z"}}},
               {"sha": "c3", "commit": {"committer": {"date": "2026-01-03T00:00:00Z"}}}]
    chk("commit at label time", commit_before(commits, "2026-01-02T00:00:00Z") == "c2")
    chk("commit before any push", commit_before(commits, "2025-12-31T00:00:00Z") is None)
    if fails:
        print("SELF-TEST FAILED: " + ", ".join(fails))
        return 1
    print("self-test ok: the copy lock catches added text, edited copy and new words, and allows an empty slot")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("GATE_BASE", "origin/main"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    return self_test() if a.self_test else run(a.base)


if __name__ == "__main__":
    sys.exit(main())
