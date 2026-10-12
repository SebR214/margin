#!/usr/bin/env python3
"""Tell SEB-301 what the watchdog found, once per outage (SEB-301). No model.

    python3 tools/watchdog_post.py down "Runner: no completed run in 2 hours; Scout: ..."
    python3 tools/watchdog_post.py up
    python3 tools/watchdog_post.py --self-test

`down` posts one line saying what is down, unless the watchdog's latest comment
on SEB-301 is already a `down` line: nothing is posted again until it recovers.
`up` posts one line only if the latest watchdog comment is a `down` line. The
latest comment is read from Linear, so the watchdog keeps no state of its own.
Env: LINEAR_API_KEY.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents"))
ISSUE = "SEB-301"
DOWN = "**Watchdog: down.** "
UP = "**Watchdog: back up.** "


def decide(state, comments):
    """The line to post, or None. `comments` are (created_at, body) pairs."""
    marked = sorted((c for c in comments if c[1].startswith((DOWN, UP))), key=lambda c: c[0])
    last_down = bool(marked) and marked[-1][1].startswith(DOWN)
    if state == "down":
        return None if last_down else "down"
    return "up" if last_down else None


def one_line(what):
    return " ".join(what.split())[:400] or "see the watchdog run"


def main(argv):
    if argv[1:2] == ["--self-test"]:
        t = lambda *b: [("2026-10-12T0%d:00" % n, x) for n, x in enumerate(b)]
        assert decide("down", []) == "down"
        assert decide("down", t(DOWN + "a")) is None, "no second post while it stays down"
        assert decide("down", t(DOWN + "a", UP + "b")) == "down"
        assert decide("up", t(DOWN + "a")) == "up"
        assert decide("up", t(DOWN + "a", UP + "b")) is None
        assert decide("up", []) is None and decide("up", t("Daily status")) is None
        assert decide("down", t(DOWN + "a", "Daily status")) is None, "other comments do not reset it"
        print("watchdog_post self-test: ok")
        return 0
    if len(argv) < 2 or argv[1] not in ("down", "up"):
        sys.exit(__doc__)
    import linear
    i = linear.find(ISSUE)
    d = linear.call("""query($id: String!) { issue(id: $id) { comments(first: 100) { nodes { createdAt body } } } }""", {"id": i["id"]})
    comments = [(c["createdAt"], c["body"]) for c in d["issue"]["comments"]["nodes"]]
    do = decide(argv[1], comments)
    if not do:
        print("nothing to post (%s, latest watchdog comment already says so)" % argv[1])
        return 0
    body = DOWN + one_line(argv[2] if len(argv) > 2 else "") if do == "down" else UP + "Every check passes again."
    linear.call("""mutation($id: String!, $b: String!) { commentCreate(input: { issueId: $id, body: $b }) { success } }""", {"id": i["id"], "b": body})
    print("posted:", body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
