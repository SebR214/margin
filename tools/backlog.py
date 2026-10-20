#!/usr/bin/env python3
"""BACKLOG.md, the build queue (SEB-301). Plain text, no model.

    python3 tools/backlog.py next            # the top unchecked job, as JSON (exit 1 if none)
    python3 tools/backlog.py sync            # copy new "Queued by Claude" items from SEB-301 comments into BACKLOG.md
    python3 tools/backlog.py tick ID PR      # tick a job (or an item without jobs) with the PR number and today's date
    python3 tools/backlog.py block ID WHY    # one line saying why a job is blocked
    python3 tools/backlog.py --self-test

Format. An item is `- [ ] N. title`. A job under it is `  - [ ] Na. title` followed by indented `files:` (backticked paths the
builder may change), `context:` (read-only) and `done when:` lines. An item with no jobs is not split yet, so it is not buildable
(the Scout splits the next 7 each Monday). When every job of an item is ticked, the item is ticked too.

`sync` runs at the start of every builder run, so nobody pastes. A comment on SEB-301 that has a line containing
"Queued by Claude" queues every bullet or numbered line under it, up to the next heading or blank-then-prose line. Each is
appended under `## Queued by Claude` once; the comment id it came from is kept in a marker so it is never copied twice.
Env for sync: LINEAR_API_KEY.
"""
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "BACKLOG.md")
ISSUE = "SEB-301"
ITEM = re.compile(r"^- \[( |x)\] (\d+)\. (.*)$")
JOB = re.compile(r"^  - \[( |x)\] (\d+[a-z]+)\. (.*)$")
QUEUED = "## Queued by Claude"


def parse(text):
    items, cur, job = [], None, None
    for n, line in enumerate(text.split("\n")):
        m = ITEM.match(line)
        if m:
            cur = {"id": m.group(2), "title": m.group(3), "done": m.group(1) == "x", "line": n, "jobs": []}
            items.append(cur)
            job = None
            continue
        m = JOB.match(line)
        if m and cur is not None:
            job = {"id": m.group(2), "title": m.group(3), "done": m.group(1) == "x", "line": n, "files": [], "context": [], "done_when": "", "blocked": "", "venues": []}
            cur["jobs"].append(job)
            continue
        if job is not None and line.startswith("    "):
            s = line.strip()
            if s.startswith("files:"):
                job["files"] = re.findall(r"`([^`\s]+)`", s)
            elif s.startswith("context:"):
                job["context"] = re.findall(r"`([^`\s]+)`", s)
            elif s.startswith("done when:"):
                job["done_when"] = s[len("done when:"):].strip()
            elif s.startswith("blocked:"):
                job["blocked"] = s[len("blocked:"):].strip()
            elif s.startswith("venue:"):
                job["venues"].append(s[len("venue:"):].strip())
        elif line.strip() and not line.startswith(" "):
            job = None
    return items


def next_job(items):
    """The first unchecked, unblocked job with files, in queue order. None when nothing is buildable."""
    for it in items:
        if it["done"]:
            continue
        for j in it["jobs"]:
            if not j["done"] and not j["blocked"] and j["files"]:
                return it, j
    return None


def today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def tick(text, ident, pr, date=None):
    """Tick job `ident` (like 1a) or an item without jobs (like 11), with the PR and date. Ticks the item when its last job is ticked."""
    date = date or today()
    lines = text.split("\n")
    items = parse(text)
    for it in items:
        if it["id"] == ident and not it["jobs"]:
            lines[it["line"]] = lines[it["line"]].replace("- [ ]", "- [x]", 1) + " (PR #%s, %s)" % (pr, date)
            return "\n".join(lines)
        for j in it["jobs"]:
            if j["id"] == ident:
                lines[j["line"]] = lines[j["line"]].replace("- [ ]", "- [x]", 1) + " (PR #%s, %s)" % (pr, date)
                if all(x["done"] or x is j for x in it["jobs"]):
                    lines[it["line"]] = lines[it["line"]].replace("- [ ]", "- [x]", 1) + " (done %s)" % date
                return "\n".join(lines)
    raise KeyError("no job or item %s in BACKLOG.md" % ident)


def block(text, ident, why, date=None):
    date = date or today()
    lines = text.split("\n")
    for it in parse(text):
        for j in it["jobs"]:
            if j["id"] == ident:
                at = j["line"] + 1
                while at < len(lines) and lines[at].startswith("    "):
                    at += 1
                lines.insert(at, "    blocked: %s (%s)" % (why.strip().replace("\n", " ")[:300], date))
                return "\n".join(lines)
        if it["id"] == ident and not it["jobs"]:
            lines.insert(it["line"] + 1, "  blocked: %s (%s)" % (why.strip().replace("\n", " ")[:300], date))
            return "\n".join(lines)
    raise KeyError(ident)


def queued_items(body):
    """The lines queued by one comment body: bullets or numbered lines after a line that mentions 'Queued by Claude'."""
    out, on = [], False
    for line in body.split("\n"):
        if re.search(r"queued by claude", line, re.I) and not re.match(r"^\s*([-*]|\d+[.)])\s", line):
            on = True
            continue
        if not on:
            continue
        m = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(?:\[[ x]\]\s*)?(.+?)\s*$", line)
        if m:
            out.append(m.group(1))
        elif line.strip() == "":
            if out:
                break          # a blank line after the list ends it
        elif line.lstrip().startswith("#") or out:
            break
    return out


def sync(text, comments):
    """Append the new queued items. `comments` is [(comment_id, body)]. Returns (new_text, [titles added])."""
    seen = set(re.findall(r"<!-- from:([0-9a-f-]+) -->", text))
    existing = {re.sub(r"\W+", " ", t.lower()).strip() for t in re.findall(r"^- \[[ x]\] \d+\. (.*?)(?: <!--.*)?$", text, re.M)}
    nums = [int(m) for m in re.findall(r"^- \[[ x]\] (\d+)\.", text, re.M)]
    nxt = max(nums or [0]) + 1
    added, block_lines = [], []
    for cid, body in comments:
        if cid in seen:
            continue
        for t in queued_items(body):
            key = re.sub(r"\W+", " ", t.lower()).strip()
            if key in existing:
                continue
            existing.add(key)
            block_lines.append("- [ ] %d. %s <!-- from:%s -->" % (nxt, t, cid))
            added.append(t)
            nxt += 1
    if not block_lines:
        return text, []
    text = text.rstrip("\n") + "\n"
    if QUEUED not in text:
        text += "\n" + QUEUED + "\nCopied from SEB-301 comments by tools/backlog.py. The Scout splits them into jobs like the rest.\n\n"
    text += "\n".join(block_lines) + "\n"
    return text, added


def linear_comments():
    sys.path.insert(0, os.path.join(ROOT, "agents"))
    import linear
    i = linear.find(ISSUE)
    out, after = [], None
    while True:
        d = linear.call("""query($id: String!, $a: String) { issue(id: $id) { comments(first: 100, after: $a) {
            nodes { id body } pageInfo { hasNextPage endCursor } } } }""", {"id": i["id"], "a": after})["issue"]["comments"]
        out += [(c["id"], c["body"]) for c in d["nodes"]]
        if not d["pageInfo"]["hasNextPage"]:
            return out
        after = d["pageInfo"]["endCursor"]


def self_test():
    text = """# t

- [ ] 1. First (x)
  - [x] 1a. done one (PR #5, 2026-10-01)
    files: `a.py`
  - [ ] 1b. second
    files: `b.py`, `c.js`
    context: `d.csv`
    done when: it works
  - [ ] 1c. third
    files: `e.py`
- [ ] 2. No jobs yet
- [ ] 3. Three
  - [ ] 3a. blocked one
    files: `f.py`
    blocked: no endpoint (2026-10-02)
  - [ ] 3b. fine
    files: `g.py`
"""
    items = parse(text)
    assert [i["id"] for i in items] == ["1", "2", "3"] and [j["id"] for j in items[0]["jobs"]] == ["1a", "1b", "1c"]
    it, j = next_job(items)
    assert j["id"] == "1b" and j["files"] == ["b.py", "c.js"] and j["context"] == ["d.csv"] and j["done_when"] == "it works"
    t2 = tick(text, "1b", 12, "2026-10-20")
    assert "- [x] 1b. second (PR #12, 2026-10-20)" in t2 and "- [ ] 1. First" in t2
    t3 = tick(tick(t2, "1c", 13, "2026-10-21"), "1c", 13) if False else tick(t2, "1c", 13, "2026-10-21")
    assert "- [x] 1. First (x) (done 2026-10-21)" in t3
    assert next_job(parse(t3))[1]["id"] == "3b", "an unsplit item and a blocked job are skipped"
    t4 = block(t3, "3b", "needs a key", "2026-10-22")
    assert next_job(parse(t4)) is None and "    blocked: needs a key (2026-10-22)" in t4
    assert "- [x] 2. No jobs yet (PR #9, 2026-10-23)" in tick(t4, "2", 9, "2026-10-23")
    body = "Queued by Claude\n\n- Add Kraken as a venue\n- [ ] Second thing\n\nSomething else here\n- not queued"
    assert queued_items(body) == ["Add Kraken as a venue", "Second thing"], queued_items(body)
    assert queued_items("**Queued by Claude (20 Oct):**\n1. One\n2. Two\n## Next\n3. no") == ["One", "Two"]
    assert queued_items("no queue here\n- a bullet") == []
    new, added = sync(text, [("c1", body), ("c2", "nothing")])
    assert added == ["Add Kraken as a venue", "Second thing"] and "## Queued by Claude" in new and "- [ ] 4. Add Kraken as a venue <!-- from:c1 -->" in new
    new2, added2 = sync(new, [("c1", body), ("c3", "Queued by Claude\n- Add Kraken as a venue\n- Third")])
    assert added2 == ["Third"] and new2.count("Add Kraken as a venue") == 1, "the same item is never copied twice"
    # the real file parses and has a buildable shape
    real = parse(open(PATH).read()) if os.path.exists(PATH) else []
    assert not real or all(i["id"].isdigit() for i in real)
    print("backlog self-test: ok")


def main(argv):
    if argv[1:2] == ["--self-test"]:
        return self_test()
    cmd = argv[1] if len(argv) > 1 else ""
    text = open(PATH).read()
    if cmd == "next":
        n = next_job(parse(text))
        if not n:
            print("{}")
            return 1
        it, j = n
        print(json.dumps({"item": it["id"], "item_title": it["title"], "job": j["id"], "title": j["title"], "files": j["files"],
                          "context": j["context"], "done_when": j["done_when"]}))
        return 0
    if cmd == "sync":
        new, added = sync(text, linear_comments())
        if added:
            open(PATH, "w").write(new)
        print("added %d: %s" % (len(added), "; ".join(added)))
        return 0
    if cmd == "tick" and len(argv) >= 4:
        open(PATH, "w").write(tick(text, argv[2], argv[3]))
        return 0
    if cmd == "block" and len(argv) >= 4:
        open(PATH, "w").write(block(text, argv[2], " ".join(argv[3:])))
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
