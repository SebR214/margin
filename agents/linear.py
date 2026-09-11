#!/usr/bin/env python3
"""The agents' interface to Linear. Linear is where the work is managed;
GitHub holds code and pull requests only.

Every command is deterministic and prints plain text, so a role file can say
"run this" instead of describing a GraphQL query.

    python3 agents/linear.py next                  # top unstarted issue, or nothing
    python3 agents/linear.py show SEB-6
    python3 agents/linear.py state SEB-6 "In Progress"
    python3 agents/linear.py say SEB-6 builder "what I did, in plain language"
    python3 agents/linear.py label SEB-6 blocked
    python3 agents/linear.py unlabel SEB-6 blocked
    python3 agents/linear.py new "title" --body-file spec.md --label commission
    python3 agents/linear.py doc "Digest 2026-09-11" --body-file digest.md
    python3 agents/linear.py issues                # everything in the project

`say` is how agents talk to each other. It stamps the role on the comment,
because the API key authenticates as Sebastian: without the stamp every comment
in every thread would read as though he wrote it. If this workspace ever
installs the agents as real Linear apps (OAuth with actor=app), the stamp
becomes redundant and can go.

Reads LINEAR_API_KEY from the environment. Never prints it. Stdlib only.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

URL = "https://api.linear.app/graphql"
TEAM_KEY = "SEB"
PROJECT_NAME = "margin.wiki"

# Who is speaking. The API key is one user, so the thread needs the stamp.
ROLES = {
    "builder":  "🔨 **Builder**",
    "reviewer": "🔍 **Reviewer**",
    "product":  "📋 **Product**",
}


def call(query, variables=None):
    key = os.environ.get("LINEAR_API_KEY")
    if not key:
        sys.exit("LINEAR_API_KEY is not set -- cannot reach Linear")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit("Linear returned %s: %s" % (e.code, e.read().decode()[:400]))
    if "errors" in out:
        sys.exit("Linear rejected the request: %s"
                 % json.dumps(out["errors"])[:600])
    return out["data"]


def project_id():
    d = call("""{ projects { nodes { id name } } }""")
    for p in d["projects"]["nodes"]:
        if p["name"] == PROJECT_NAME:
            return p["id"]
    sys.exit("no project named %r in this workspace" % PROJECT_NAME)


def states():
    d = call("""{ workflowStates { nodes { id name type } } }""")
    return {s["name"]: s for s in d["workflowStates"]["nodes"]}


ISSUE_FIELDS = """
  id identifier title url priority sortOrder
  state { name type }
  labels { nodes { name } }
  description
"""


def issues_in_project():
    pid = project_id()
    d = call("""query($id: String!) {
      project(id: $id) { issues(first: 100) { nodes { %s } } }
    }""" % ISSUE_FIELDS, {"id": pid})
    return d["project"]["issues"]["nodes"]


def find(ident):
    """Look up an issue by its key, e.g. SEB-8."""
    ident = ident.strip().upper()
    if "-" not in ident or not ident.split("-")[1].isdigit():
        sys.exit("expected an issue key like SEB-8, got %r" % ident)
    number = int(ident.split("-")[1])
    d = call("""query($n: Float!, $k: String!) {
      issues(filter: { number: { eq: $n }, team: { key: { eq: $k } } })
        { nodes { %s } }
    }""" % ISSUE_FIELDS, {"n": number, "k": TEAM_KEY})
    n = d["issues"]["nodes"]
    if not n:
        sys.exit("no issue %s" % ident)
    return n[0]


def line(i):
    lab = ",".join(l["name"] for l in i["labels"]["nodes"])
    return "%-8s [%-11s] p%s %s%s" % (
        i["identifier"], i["state"]["name"], i["priority"], i["title"],
        ("  <%s>" % lab) if lab else "")


def cmd_next(_):
    """The top unstarted issue, skipping anything blocked.

    Order is Linear's own: priority first, then the manual position in the
    project. Whatever sits at the top of the Todo column is what gets built.
    """
    todo = [i for i in issues_in_project()
            if i["state"]["type"] == "unstarted"
            and "blocked" not in [l["name"] for l in i["labels"]["nodes"]]
            and "needs-sebastian" not in [l["name"] for l in i["labels"]["nodes"]]]
    if not todo:
        print("NOTHING TO DO")
        return
    todo.sort(key=lambda i: (i["priority"] or 99, i["sortOrder"]))
    print(todo[0]["identifier"])


def cmd_issues(_):
    for i in sorted(issues_in_project(),
                    key=lambda x: (x["priority"] or 99, x["sortOrder"])):
        print(line(i))


def cmd_show(a):
    i = find(a.ident)
    print(line(i))
    print("url: %s" % i["url"])
    print("-" * 72)
    print(i["description"] or "(no description)")


def cmd_state(a):
    i = find(a.ident)
    st = states()
    if a.state not in st:
        sys.exit("no state %r -- have: %s" % (a.state, ", ".join(st)))
    call("""mutation($id: String!, $s: String!) {
      issueUpdate(id: $id, input: { stateId: $s }) { success }
    }""", {"id": i["id"], "s": st[a.state]["id"]})
    print("%s -> %s" % (i["identifier"], a.state))


def cmd_say(a):
    i = find(a.ident)
    if a.role not in ROLES:
        sys.exit("role must be one of: %s" % ", ".join(ROLES))
    text = open(a.body_file).read() if a.body_file else a.text
    if not text or not text.strip():
        sys.exit("refusing to post an empty comment")
    body = "%s\n\n%s" % (ROLES[a.role], text.strip())
    call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": body})
    print("commented on %s as %s" % (i["identifier"], a.role))


def _label_id(name):
    d = call("""{ issueLabels { nodes { id name } } }""")
    for l in d["issueLabels"]["nodes"]:
        if l["name"].lower() == name.lower():
            return l["id"]
    sys.exit("no label %r" % name)


def cmd_label(a):
    i = find(a.ident)
    call("""mutation($id: String!, $l: String!) {
      issueAddLabel(id: $id, labelId: $l) { success }
    }""", {"id": i["id"], "l": _label_id(a.label)})
    print("%s +%s" % (i["identifier"], a.label))


def cmd_unlabel(a):
    i = find(a.ident)
    call("""mutation($id: String!, $l: String!) {
      issueRemoveLabel(id: $id, labelId: $l) { success }
    }""", {"id": i["id"], "l": _label_id(a.label)})
    print("%s -%s" % (i["identifier"], a.label))


def cmd_new(a):
    body = open(a.body_file).read() if a.body_file else (a.body or "")
    team = call("""{ teams(filter: { key: { eq: "%s" } }) { nodes { id } } }"""
                % TEAM_KEY)["teams"]["nodes"][0]["id"]
    inp = {"teamId": team, "projectId": project_id(), "title": a.title,
           "description": body, "stateId": states()["Todo"]["id"],
           "priority": a.priority}
    if a.label:
        inp["labelIds"] = [_label_id(x) for x in a.label]
    r = call("""mutation($i: IssueCreateInput!) {
      issueCreate(input: $i) { issue { identifier url } }
    }""", {"i": inp})
    i = r["issueCreate"]["issue"]
    print("%s %s" % (i["identifier"], i["url"]))


def cmd_doc(a):
    body = open(a.body_file).read() if a.body_file else (a.body or "")
    r = call("""mutation($i: DocumentCreateInput!) {
      documentCreate(input: $i) { document { id title url } }
    }""", {"i": {"title": a.title, "content": body, "projectId": project_id()}})
    d = r["documentCreate"]["document"]
    print("%s %s" % (d["title"], d["url"]))


def cmd_docs(_):
    d = call("""{ documents { nodes { title url createdAt } } }""")
    for x in d["documents"]["nodes"]:
        print("%s  %s  %s" % (x["createdAt"][:10], x["title"], x["url"]))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)

    s.add_parser("next").set_defaults(fn=cmd_next)
    s.add_parser("issues").set_defaults(fn=cmd_issues)
    s.add_parser("docs").set_defaults(fn=cmd_docs)

    x = s.add_parser("show"); x.add_argument("ident"); x.set_defaults(fn=cmd_show)
    x = s.add_parser("state"); x.add_argument("ident"); x.add_argument("state")
    x.set_defaults(fn=cmd_state)
    x = s.add_parser("say"); x.add_argument("ident"); x.add_argument("role")
    x.add_argument("text", nargs="?"); x.add_argument("--body-file")
    x.set_defaults(fn=cmd_say)
    x = s.add_parser("label"); x.add_argument("ident"); x.add_argument("label")
    x.set_defaults(fn=cmd_label)
    x = s.add_parser("unlabel"); x.add_argument("ident"); x.add_argument("label")
    x.set_defaults(fn=cmd_unlabel)
    x = s.add_parser("new"); x.add_argument("title"); x.add_argument("--body")
    x.add_argument("--body-file"); x.add_argument("--label", action="append")
    x.add_argument("--priority", type=int, default=3); x.set_defaults(fn=cmd_new)
    x = s.add_parser("doc"); x.add_argument("title"); x.add_argument("--body")
    x.add_argument("--body-file"); x.set_defaults(fn=cmd_doc)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
