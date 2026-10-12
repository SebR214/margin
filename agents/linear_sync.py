#!/usr/bin/env python3
"""Keep a builder issue's Linear state true to its PR (SEB-301). No model.

    python3 agents/linear_sync.py merged SEB-300 123
    python3 agents/linear_sync.py failed SEB-300 123 "method-change"

`merged`: the PR landed, so the issue goes to Done (the Scout waits on SEB-300
being Done). `failed`: a check on the PR failed, so the issue gets the label
`needs-claude` and one comment, so the builder never retries it and the Scout
never stalls on it. Both are safe to run twice. Env: LINEAR_API_KEY.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linear  # noqa: E402

STUCK = "needs-claude"


def comment(i, text):
    linear.call("""mutation($id: String!, $b: String!) {
      commentCreate(input: { issueId: $id, body: $b }) { success }
    }""", {"id": i["id"], "b": text})


def merged(ident, pr):
    i = linear.find(ident)
    if i["state"]["type"] == "completed":
        print("%s is already Done" % ident)
        return
    st = linear.states()
    linear.call("""mutation($id: String!, $s: String!) {
      issueUpdate(id: $id, input: { stateId: $s }) { success }
    }""", {"id": i["id"], "s": st["Done"]["id"]})
    comment(i, "PR #%s merged. Set to Done." % pr)
    print("%s -> Done" % ident)


def failed(ident, pr, what):
    i = linear.find(ident)
    if STUCK in {l["name"].lower() for l in i["labels"]["nodes"]}:
        print("%s already has %s" % (ident, STUCK))
        return
    linear.call("""mutation($id: String!, $l: String!) {
      issueAddLabel(id: $id, labelId: $l) { success }
    }""", {"id": i["id"], "l": linear._label_id(STUCK)})
    comment(i, "PR #%s failed a check (%s). Labelled `%s`: the builder will not retry it, "
               "and the Scout does not wait on it." % (pr, what or "see the PR", STUCK))
    print("%s +%s" % (ident, STUCK))


def main(argv):
    if len(argv) < 4 or argv[1] not in ("merged", "failed"):
        sys.exit(__doc__)
    if argv[1] == "merged":
        merged(argv[2], argv[3])
    else:
        failed(argv[2], argv[3], argv[4] if len(argv) > 4 else "")


if __name__ == "__main__":
    main(sys.argv)
