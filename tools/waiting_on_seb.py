#!/usr/bin/env python3
"""One email when something has waited on Seb for more than 24 hours (SEB-301, Seb's rule of 20 Oct). No model.

    python3 tools/waiting_on_seb.py            # list what waits, and post if the list changed
    python3 tools/waiting_on_seb.py --print    # only print
    python3 tools/waiting_on_seb.py --self-test

What counts as waiting: a Linear issue in the margin.wiki project labelled `needs-sebastian` that is not Done or Canceled and has not
been touched for 24 hours, and an open pull request that has been open for more than 24 hours and is not a draft of a job in progress
(the PRs automerge leaves open on purpose). The email is a comment, "Waiting on you: {n}", with one line each and a link, on the GitHub
issue titled "Waiting on you" (created on first use), mentioning the repository owner: GitHub sends that to the address on his account.
It is posted only when the list differs from the last one posted (a hash of the items is kept in the comment). An empty list posts
nothing. Env: GH_TOKEN (issues: write), GITHUB_REPOSITORY, LINEAR_API_KEY.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents"))
AFTER = datetime.timedelta(hours=24)
TITLE = "Waiting on you"
MARK = re.compile(r"<!-- waiting:([0-9a-f]{12}) -->")


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def signature(items):
    return hashlib.sha256("\n".join(sorted(i["key"] for i in items)).encode()).hexdigest()[:12]


def message(items, owner):
    lines = ["@%s Waiting on you: %d" % (owner, len(items)), ""]
    lines += ["- %s: %s" % (i["text"], i["url"]) for i in items]
    return "\n".join(lines) + "\n\n<!-- waiting:%s -->" % signature(items)


def decide(items, last_body):
    """Post only when something waits and the list is not the one already posted."""
    if not items:
        return False
    m = MARK.search(last_body or "")
    return not (m and m.group(1) == signature(items))


def linear_items(now):
    import linear
    out = []
    for i in linear.issues_in_project():
        names = {l["name"].lower() for l in i["labels"]["nodes"]}
        if "needs-sebastian" in names and i["state"]["type"] not in ("completed", "canceled"):
            upd = i.get("updatedAt")
            if upd and now - ts(upd) < AFTER:
                continue
            out.append({"key": "linear:" + i["identifier"], "text": "%s %s" % (i["identifier"], i["title"]), "url": i["url"]})
    return out


def pr_items(now, get):
    out = []
    for p in get("pulls?state=open&per_page=50"):
        if p.get("draft") and re.search(r"waits for Seb", p["title"]) is None:
            continue
        if now - ts(p["created_at"]) >= AFTER:
            out.append({"key": "pr:%d" % p["number"], "text": "PR #%d %s" % (p["number"], p["title"]), "url": p["html_url"]})
    return out


def gh(path, method="GET", data=None):
    cmd = ["gh", "api", "-X", method, "repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path)]
    if data:
        for k, v in data.items():
            cmd += ["-f", "%s=%s" % (k, v)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("gh api %s failed: %s" % (path, r.stderr[-300:]))
    return json.loads(r.stdout) if r.stdout.strip() else None


def main(argv):
    if "--self-test" in argv:
        return self_test()
    now = datetime.datetime.now(datetime.timezone.utc)
    items = linear_items(now) + pr_items(now, gh)
    print("waiting on Seb: %d" % len(items))
    for i in items:
        print("  - %s" % i["text"])
    if "--print" in argv:
        return 0
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    issues = [x for x in gh("issues?state=open&per_page=100") if x["title"] == TITLE and "pull_request" not in x]
    last = ""
    if issues:
        cs = gh("issues/%d/comments?per_page=100" % issues[0]["number"])
        last = cs[-1]["body"] if cs else ""
    if not decide(items, last):
        print("nothing to send (%s)" % ("nothing waits" if not items else "the list is the one already sent"))
        return 0
    number = issues[0]["number"] if issues else gh("issues", "POST", {"title": TITLE, "body": "One comment here, each time the list of what waits on Seb for over 24 hours changes (tools/waiting_on_seb.py)."})["number"]
    gh("issues/%d/comments" % number, "POST", {"body": message(items, owner)})
    print("posted on issue #%d" % number)
    return 0


def self_test():
    a = [{"key": "linear:SEB-213", "text": "SEB-213 switch the API on", "url": "https://linear.app/x"}]
    b = a + [{"key": "pr:9", "text": "PR #9 x", "url": "https://github.com/o/r/pull/9"}]
    assert signature(a) != signature(b) and signature(a) == signature(list(a))
    msg = message(a, "SebR214")
    assert msg.startswith("@SebR214 Waiting on you: 1") and "- SEB-213 switch the API on: https://linear.app/x" in msg
    assert decide(a, "") and decide(a, "something else")
    assert not decide(a, msg), "the same list is not sent twice"
    assert decide(b, msg), "a changed list is sent"
    assert not decide([], msg), "nothing waiting, nothing sent"
    now = datetime.datetime(2026, 10, 20, 12, tzinfo=datetime.timezone.utc)
    prs = [{"number": 1, "title": "SEB-1 x", "html_url": "u1", "created_at": "2026-10-19T09:00:00Z", "draft": False},
           {"number": 2, "title": "SEB-2 y", "html_url": "u2", "created_at": "2026-10-20T09:00:00Z", "draft": False},
           {"number": 3, "title": "SEB-3 z", "html_url": "u3", "created_at": "2026-10-10T09:00:00Z", "draft": True}]
    got = pr_items(now, lambda p: prs)
    assert [i["key"] for i in got] == ["pr:1"], got
    print("waiting_on_seb self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
