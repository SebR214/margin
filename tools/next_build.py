#!/usr/bin/env python3
"""Which Linear issue does the Claude builder take next? No model. (claude_builder.yml)

Asks Linear for issues with the label `build` in project margin.wiki (only that project) and prints
one JSON object, or nothing at all (exit 0) when there is no job. Order:

  1. a `build` issue In Review with a comment from Seb newer than the builder's last comment
  2. else the top `build` issue in Todo (priority first, then oldest)

Nothing is printed if 3 builds already started today (UTC): the count is the builder's "Started"
comments of today. Issues labelled blocked, needs-claude or needs-sebastian are skipped.

    python3 tools/next_build.py            # needs LINEAR_API_KEY
    python3 tools/next_build.py --self-test
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents"))

LABEL = "build"
SKIP = {"blocked", "needs-claude", "needs-sebastian"}
DAILY_LIMIT = 3
BUILDER = "🔨 **Builder**"
STAMPS = ("🔨 **Builder**", "🔍 **Reviewer**", "📋 **Product**", "🕵️ **Critic**")
STARTED = BUILDER + "\n\nStarted"


def is_seb(c):
    """An unstamped comment is Seb's own (agents/linear.py)."""
    return not c["body"].startswith(STAMPS)


def prio(i):
    p = i.get("priority") or 0
    return (p if p else 5, i.get("createdAt") or "")


def started_today(issues, today):
    return sum(1 for i in issues for c in i["comments"]["nodes"]
               if c["body"].startswith(STARTED) and c["createdAt"][:10] == today)


def pick(issues, today):
    """The issue to build, or None."""
    issues = [i for i in issues
              if not SKIP & {l["name"].lower() for l in i["labels"]["nodes"]}]
    if started_today(issues, today) >= DAILY_LIMIT:
        return None, "limit"
    review = []
    for i in issues:
        if i["state"]["name"] != "In Review":
            continue
        cs = sorted(i["comments"]["nodes"], key=lambda c: c["createdAt"])
        mine = [c["createdAt"] for c in cs if c["body"].startswith(BUILDER)]
        last = max(mine) if mine else ""
        if any(is_seb(c) and c["createdAt"] > last for c in cs):
            review.append(i)
    if review:
        return sorted(review, key=prio)[0], "resume"
    todo = [i for i in issues if i["state"]["name"] == "Todo"]
    if todo:
        return sorted(todo, key=prio)[0], "new"
    return None, "none"


def fetch():
    import linear
    d = linear.call("""query($id: String!) {
      project(id: $id) { issues(first: 100, filter: { labels: { name: { eq: "%s" } } }) { nodes {
        identifier title url description priority createdAt
        state { name }
        labels { nodes { name } }
        comments(first: 100) { nodes { body createdAt } }
      } } }
    }""" % LABEL, {"id": linear.project_id()})
    return d["project"]["issues"]["nodes"]


def main():
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    issue, why = pick(fetch(), today)
    if not issue:
        print("next_build: no job (%s)" % why, file=sys.stderr)
        return 0
    cs = sorted(issue["comments"]["nodes"], key=lambda c: c["createdAt"])
    print(json.dumps({
        "id": issue["identifier"], "title": issue["title"], "url": issue["url"],
        "description": issue.get("description") or "", "mode": why,
        "comments": [{"from": "Seb" if is_seb(c) else "agent", "at": c["createdAt"], "body": c["body"]}
                     for c in cs],
    }))
    return 0


def self_test():
    def iss(ident, state, comments=(), labels=(), pr=0, created="2026-11-01"):
        return {"identifier": ident, "title": ident, "priority": pr, "createdAt": created,
                "state": {"name": state}, "labels": {"nodes": [{"name": n} for n in labels]},
                "comments": {"nodes": [{"body": b, "createdAt": t} for b, t in comments]}}
    today = "2026-11-05"
    S = BUILDER + "\n\nStarted"
    P = BUILDER + "\n\nPR link"
    fails = []

    def chk(name, got, want):
        if got != want:
            fails.append("%s: %r != %r" % (name, got, want))
    chk("none", pick([], today)[1], "none")
    chk("todo", pick([iss("A", "Todo"), iss("B", "Todo", pr=1)], today)[0]["identifier"], "B")
    chk("todo order", pick([iss("A", "Todo", created="2026-11-02"), iss("B", "Todo", created="2026-11-01")], today)[0]["identifier"], "B")
    rv = iss("R", "In Review", [(S, "2026-11-04T10:00"), (P, "2026-11-04T11:00")])
    chk("review idle", pick([rv], today)[1], "none")
    rv2 = iss("R", "In Review", [(S, "2026-11-04T10:00"), (P, "2026-11-04T11:00"), ("please change X", "2026-11-04T12:00")])
    chk("review comment", pick([rv2, iss("T", "Todo")], today)[0]["identifier"], "R")
    chk("review answered", pick([iss("R", "In Review", [(P, "2026-11-04T11:00"), ("x", "2026-11-04T12:00"), (P, "2026-11-04T13:00")])], today)[1], "none")
    st = [iss("D%d" % n, "Done", [(S, "2026-11-05T0%d:00:00" % n)]) for n in range(3)]
    chk("limit", pick(st + [iss("T", "Todo")], today)[1], "limit")
    chk("yesterday", pick(st[:2] + [iss("Y", "Done", [(S, "2026-11-04T09:00:00")]), iss("T", "Todo")], today)[0]["identifier"], "T")
    chk("skip", pick([iss("T", "Todo", labels=["blocked"])], today)[1], "none")
    if fails:
        print("\n".join(fails))
        return 1
    print("next_build self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
