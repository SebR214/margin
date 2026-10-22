#!/usr/bin/env python3
"""BACKLOG.md, the build queue (SEB-301). Plain text, no model.

    python3 tools/backlog.py next            # the top unchecked job, as JSON (exit 1 if none)
    python3 tools/backlog.py sync            # copy new "Queued by Claude" items from SEB-301 comments into BACKLOG.md
    python3 tools/backlog.py tick ID PR      # tick a job (or an item without jobs) with the PR number and today's date
    python3 tools/backlog.py block ID WHY    # one line saying why a job is blocked
    python3 tools/backlog.py verify-data     # tick built collection jobs whose rows landed; block the ones whose rows did not (rule d)
    python3 tools/backlog.py post TEXT       # one line on SEB-301 (watchdog.yml, after the BACKLOG.md change is on main)
    python3 tools/backlog.py --self-test

Format. An item is `- [ ] N. title`. A job under it is `  - [ ] Na. title` followed by indented `files:` (backticked paths the
builder may change), `context:` (read-only) and `done when:` lines. An item with no jobs is not split yet, so it is not buildable
(the Scout splits the next 7 each Monday). When every job of an item is ticked, the item is ticked too.

A file too big to send whole (collector.py is 103,000 characters) is listed in `files:` and gets one or more
`excerpt: `path` `start regex` `end regex`` lines: the builder sends only those parts (from the first line matching start to the
next line matching end) and the model changes the file with find-and-replace edits, never a full copy.

Done means data (SEB-301, 21 Oct). A job that adds or changes collection (its files include a collector*.py or collect.yml) must
have a `rows:` line: the CSV its rows land in and, optionally, a value one column of those rows must hold (`rows: `data/samples.csv`
`USD->PHP``). The builder does not tick such a job when it opens the PR; it writes `built: PR #N (date)`, and the job is not built
again. `verify-data` runs every 30 minutes (watchdog.yml): once the PR is merged and a row with that value and a timestamp after the
merge is on main, the job is ticked. If none lands within 2 hours of the merge, the `built:` line goes, the job is blocked with why,
and the why is posted on SEB-301. A PR closed without merging is treated the same way.

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
            job = {"id": m.group(2), "title": m.group(3), "done": m.group(1) == "x", "line": n, "files": [], "context": [], "done_when": "", "blocked": "", "venues": [],
                   "rows": [], "built": "", "excerpts": [], "track": ""}
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
            elif s.startswith("rows:"):
                job["rows"] = re.findall(r"`([^`]+)`", s)[:2]
            elif s.startswith("excerpt:"):
                job["excerpts"].append(re.findall(r"`([^`]+)`", s)[:3])
            elif s.startswith("built:"):
                job["built"] = s[len("built:"):].strip()
            elif s.startswith("track:"):
                job["track"] = s[len("track:"):].strip()
        elif line.strip() and not line.startswith(" "):
            job = None
    return items


COLLECTION = re.compile(r"^(collector[^/]*\.py|\.github/workflows/collect\.yml)$")


def is_collection(job):
    """A job that adds or changes collection: ticked only when its rows land (rule d)."""
    return any(COLLECTION.match(p) for p in job["files"])


def next_job(items, track=""):
    """The first unchecked, unblocked job with files, in queue order, that is not built and waiting for its rows. None when nothing
    is buildable. `track` is the builder asking: a job with a `track: aider` line belongs to the Aider builder (SEB-301, track A,
    tools/aider_builder.py) and the one-call builder (track "") never takes it."""
    for it in items:
        if it["done"]:
            continue
        for j in it["jobs"]:
            if not j["done"] and not j["blocked"] and not j["built"] and j["files"] and j["track"] == track:
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


def _job(items, ident):
    for it in items:
        for j in it["jobs"]:
            if j["id"] == ident:
                return it, j
    raise KeyError("no job %s in BACKLOG.md" % ident)


def _field_end(lines, at):
    at += 1
    while at < len(lines) and lines[at].startswith("    "):
        at += 1
    return at


def mark_built(text, ident, pr, date=None):
    """A collection job's PR is open: `built: PR #N (date)` instead of a tick, so it is not built again and is ticked only when its rows land."""
    lines = text.split("\n")
    it, j = _job(parse(text), ident)
    lines.insert(_field_end(lines, j["line"]), "    built: PR #%s (%s)" % (pr, date or today()))
    return "\n".join(lines)


def unbuild(text, ident):
    """Drop a job's `built:` line."""
    lines = text.split("\n")
    it, j = _job(parse(text), ident)
    end = _field_end(lines, j["line"])
    keep = [l for l in lines[j["line"] + 1:end] if not l.strip().startswith("built:")]
    return "\n".join(lines[:j["line"] + 1] + keep + lines[end:])


def _ts(s):
    s = (s or "").strip().replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def rows_after(path, value, since):
    """True when `path` has a row with a timestamp (ts_utc or ts) at or after `since` and, if `value` is given, a column equal to it."""
    import csv
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return False
    with open(full, newline="") as f:
        for r in csv.DictReader(f):
            t = _ts(r.get("ts_utc") or r.get("ts"))
            if t and t >= since and (not value or value in r.values()):
                return True
    return False


GRACE = datetime.timedelta(hours=2)


def verify_data(text, pr_state, has_rows, now=None):
    """Rule d. `pr_state(n)` -> ("open" | "closed" | "merged", merged_at or None); `has_rows(path, value, since)` -> bool.
    Returns (new_text, [(job id, 'ticked' | 'failed', why)])."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = []
    for it in parse(text):
        for j in it["jobs"]:
            if j["done"] or not j["built"]:
                continue
            m = re.search(r"#(\d+)", j["built"])
            if not m:
                continue
            n = m.group(1)
            state, merged = pr_state(n)
            if state == "open":
                continue
            path, value = (j["rows"] + [None, None])[:2]
            if state == "merged" and path and has_rows(path, value, merged):
                text = tick(unbuild(text, j["id"]), j["id"], n, now.date().isoformat())
                out.append((j["id"], "ticked", ""))
                continue
            if state == "merged" and path and now < merged + GRACE:
                continue
            if state != "merged":
                why = "PR #%s was closed without merging" % n
            elif not path:
                why = "PR #%s merged but the job has no rows: line, so its data cannot be checked" % n
            else:
                why = "no rows%s in %s within 2 hours of PR #%s's merge (%s UTC)" % (
                    " for %s" % value if value else "", path, n, merged.strftime("%d %b %H:%M"))
            text = block(unbuild(text, j["id"]), j["id"], why, now.date().isoformat())
            out.append((j["id"], "failed", why))
    return text, out


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


def gh_pr_state(n):
    import subprocess
    d = json.loads(subprocess.run(["gh", "api", "repos/%s/pulls/%s" % (os.environ.get("GITHUB_REPOSITORY", "SebR214/margin"), n)],
                                  capture_output=True, text=True, check=True).stdout)
    if d.get("merged_at"):
        return "merged", _ts(d["merged_at"])
    return ("open" if d.get("state") == "open" else "closed"), None


def verify_main(text):
    """Write BACKLOG.md if a job was ticked or failed, and print one line per change (watchdog.yml commits it and posts the failures)."""
    new, changes = verify_data(text, gh_pr_state, rows_after)
    if new != text:
        open(PATH, "w").write(new)
    for ident, what, why in changes:
        print("%s %s%s" % (ident, what, ": " + why if why else ""))
    return 0


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
    # rule d: a built collection job waits for its rows, then is ticked or blocked
    d = """- [ ] 1. Route
  - [ ] 1a. add USD->PHP
    files: `collector.py` `.github/workflows/collect.yml`
    rows: `data/samples.csv` `USD->PHP`
  - [ ] 1b. page
    files: `js/a.js`
"""
    dj = parse(d)[0]["jobs"]
    assert is_collection(dj[0]) and not is_collection(dj[1]) and dj[0]["rows"] == ["data/samples.csv", "USD->PHP"]
    b = mark_built(d, "1a", 40, "2026-10-21")
    assert "    built: PR #40 (2026-10-21)" in b and next_job(parse(b))[1]["id"] == "1b", "a built job is not built again"
    utc = datetime.timezone.utc
    merged = datetime.datetime(2026, 10, 21, 5, 0, tzinfo=utc)
    st = lambda s: (lambda n: (s, merged if s == "merged" else None))
    assert verify_data(b, st("open"), lambda *a: False)[1] == []
    assert verify_data(b, st("merged"), lambda *a: False, merged + datetime.timedelta(hours=1))[1] == [], "inside 2 hours: wait"
    seen = []
    t5, r5 = verify_data(b, st("merged"), lambda p, v, s: seen.append((p, v, s)) or True, merged + datetime.timedelta(minutes=40))
    assert r5 == [("1a", "ticked", "")] and "- [x] 1a. add USD->PHP (PR #40, 2026-10-21)" in t5 and "built:" not in t5
    assert seen == [("data/samples.csv", "USD->PHP", merged)]
    t6, r6 = verify_data(b, st("merged"), lambda *a: False, merged + datetime.timedelta(hours=2, minutes=1))
    assert r6[0][:2] == ("1a", "failed") and "within 2 hours of PR #40" in r6[0][2] and "built:" not in t6 and "- [ ] 1a." in t6
    assert "    blocked: no rows for USD->PHP in data/samples.csv within 2 hours" in t6 and next_job(parse(t6))[1]["id"] == "1b"
    t7, r7 = verify_data(b, st("closed"), lambda *a: True, merged)
    assert r7[0][1] == "failed" and "closed without merging" in r7[0][2]
    assert _ts("2026-10-21T02:06:35.260163+00:00") > _ts("2026-10-21T02:00:00Z")
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
    if cmd == "verify-data":
        return verify_main(text)
    if cmd == "post" and len(argv) >= 3:
        sys.path.insert(0, os.path.join(ROOT, "agents"))
        import linear
        i = linear.find(ISSUE)
        linear.call("""mutation($id: String!, $b: String!) { commentCreate(input: { issueId: $id, body: $b }) { success } }""",
                    {"id": i["id"], "b": "⚙️ **Builder:** " + " ".join(argv[2:])})
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
