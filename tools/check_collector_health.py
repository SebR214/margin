#!/usr/bin/env python3
"""Is collection alive? One rule, one alarm (SEB-301, 31 Oct). No model.

    python3 tools/check_collector_health.py              # print the verdict; exit 0 = alive, 1 = down, 2 = could not tell
    python3 tools/check_collector_health.py --post       # the same, and tell SEB-301 on Linear (collector_watchdog.yml)
    python3 tools/check_collector_health.py --self-test

Collection is DOWN if no commit whose message starts with "sample" has landed on main in the last 90 minutes. Nothing else
counts: not a green run, not a red one, not the freshness of a file. collect.yml writes that commit only when its rows have
reached main, so it is the one fact that says the data is arriving.

--post comments on Linear SEB-301:
  - when collection goes down: "down since {time}, {n} hours lost so far";
  - again every 12 hours while it stays down;
  - once when it is back: the gap, from the last sample before it to the first sample after it, in hours.
No GitHub issue, no email. The state is read from the latest "Collection:" comment on SEB-301, so nothing is kept elsewhere.
Env: GH_TOKEN (read access to the repo), GH_REPO (default SebR214/margin), LINEAR_API_KEY for --post.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents"))
REPO = os.environ.get("GH_REPO", "SebR214/margin")
ISSUE = "SEB-301"
LIMIT = dt.timedelta(minutes=90)
REPEAT = dt.timedelta(hours=12)
COMMENT_PAGE = 100
MAX_COMMENT_PAGES = 200                          # 20,000 comments; past that it fails loud rather than guess
PAGES = 5                                        # 100 commits a page
DOWN = "**Collection: down.** "
UP = "**Collection: back up.** "
SINCE = re.compile(r"<!-- since:(\S+) -->")


def parse(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def when(t):
    return t.strftime("%-d %b %H:%M UTC")


def hours(a, b):
    return round((b - a).total_seconds() / 3600, 1)


def fetch_sample_times():
    """Commit times of every 'sample ...' commit among the newest PAGES*100 commits on main, newest first. Raises on an API error."""
    out = []
    for page in range(1, PAGES + 1):
        r = subprocess.run(["gh", "api", f"repos/{REPO}/commits?sha=main&per_page=100&page={page}"],
                           capture_output=True, text=True, check=True, cwd=ROOT).stdout
        commits = json.loads(r)
        for c in commits:
            if c["commit"]["message"].startswith("sample"):
                out.append(parse(c["commit"]["committer"]["date"]))
        if len(commits) < 100:
            break
    return sorted(out, reverse=True)


def verdict(now, samples):
    """(down?, newest sample time or None, one line)."""
    last = samples[0] if samples else None
    if last is None:
        return True, None, "collection DOWN: no commit starting with 'sample' in the newest %d commits on main" % (PAGES * 100)
    age = now - last
    mins = int(age.total_seconds() // 60)
    if age > LIMIT:
        return True, last, "collection DOWN: last sample commit %s, %d min ago (limit %d)" % (when(last), mins, LIMIT.total_seconds() // 60)
    return False, last, "collection healthy: last sample commit %s, %d min ago (limit %d)" % (when(last), mins, LIMIT.total_seconds() // 60)


def decide(down, comments, now):
    """'down' (post the first or a 12-hour repeat), 'up' (post the recovery) or None. comments: (created_at, body) pairs."""
    marked = sorted((c for c in comments if c[1].startswith((DOWN, UP))), key=lambda c: c[0])
    last = marked[-1] if marked else None
    was_down = last is not None and last[1].startswith(DOWN)
    if down:
        return "down" if (not was_down or now - last[0] >= REPEAT) else None
    return "up" if was_down else None


def down_body(now, last):
    if last is None:
        return DOWN + "No commit starting with 'sample' in the newest %d commits on main, so the start of the outage is not known." % (PAGES * 100)
    return (DOWN + "Down since %s (the last sample commit). %s hours lost so far, at %s. Rows for those hours were not collected and cannot be "
            "backfilled. <!-- since:%s -->" % (when(last), hours(last, now), when(now), last.isoformat()))


def up_body(comments, samples):
    """The recovery line: the gap runs from the last sample before the outage (read from the latest down comment) to the first after it."""
    downs = sorted((c for c in comments if c[1].startswith(DOWN)), key=lambda c: c[0])
    m = SINCE.search(downs[-1][1]) if downs else None
    if not m:
        return UP + "Sample commits are landing again (%s is the newest)." % when(samples[0])
    since = parse(m.group(1))
    after = sorted(s for s in samples if s > since)
    first = after[0] if after else samples[0]
    return UP + "Down from %s to %s: %s hours lost. Sample commits are landing again. <!-- gap:%s..%s -->" % (
        when(since), when(first), hours(since, first), since.isoformat(), first.isoformat())


def all_comments(page):
    """Every comment of the issue as (created_at, body), by following the cursor to the last page. page(cursor) returns one
    connection: {"nodes": [...], "pageInfo": {"hasNextPage": bool, "endCursor": str}}. SEB-301 gets a daily status and other
    agents' comments, so one page can never be trusted to hold this script's own latest line."""
    out, cursor = [], None
    for _ in range(MAX_COMMENT_PAGES):
        conn = page(cursor)
        out.extend((parse(c["createdAt"]), c["body"]) for c in conn["nodes"])
        info = conn["pageInfo"]
        if not info["hasNextPage"]:
            return out
        cursor = info["endCursor"]
    raise RuntimeError("more than %d comments on %s, not reading them all" % (MAX_COMMENT_PAGES * COMMENT_PAGE, ISSUE))


def post(now, down, last, samples):
    import linear
    i = linear.find(ISSUE)

    def page(cursor):
        d = linear.call("""query($id: String!, $n: Int!, $after: String) { issue(id: $id) {
          comments(first: $n, after: $after) { nodes { createdAt body } pageInfo { hasNextPage endCursor } } } }""",
                        {"id": i["id"], "n": COMMENT_PAGE, "after": cursor})
        return d["issue"]["comments"]

    comments = all_comments(page)
    do = decide(down, comments, now)
    if not do:
        print("nothing to post")
        return
    body = down_body(now, last) if do == "down" else up_body(comments, samples)
    linear.call("""mutation($id: String!, $b: String!) { commentCreate(input: { issueId: $id, body: $b }) { success } }""", {"id": i["id"], "b": body})
    print("posted on %s: %s" % (ISSUE, body))


def self_test():
    t = lambda h, m=0: dt.datetime(2026, 10, 28, h, m, tzinfo=dt.timezone.utc)
    n = lambda h, m=0: dt.datetime(2026, 10, 31, h, m, tzinfo=dt.timezone.utc)
    # the rule: 90 minutes since the newest sample commit, nothing else
    assert verdict(t(21, 30), [t(20, 8)])[0] is False, "81 minutes is alive"
    assert verdict(t(21, 38), [t(20, 8)])[0] is False, "exactly 90 minutes is alive"
    assert verdict(t(21, 39), [t(20, 8)])[0] is True, "91 minutes is down"
    assert verdict(t(21, 39), [t(21, 30), t(20, 8)])[0] is False, "the newest sample counts"
    d, last, line = verdict(n(4, 24), [t(20, 48)])
    assert d and last == t(20, 48) and "DOWN" in line and "28 Oct 20:48 UTC" in line, line
    assert verdict(n(4, 24), [])[0] is True and verdict(n(4, 24), [])[1] is None, "no sample commit at all is down"
    # 'sample' is the only message that counts
    assert "sample 2026-10-28T20:48Z".startswith("sample") and not "aider builder run".startswith("sample")
    # what is posted, and when
    c = lambda h, body: (n(h), body)
    assert decide(True, [], n(5)) == "down"
    first = c(5, down_body(n(5), t(20, 48)))
    assert decide(True, [first], n(16, 59)) is None, "no repeat inside 12 hours"
    assert decide(True, [first], n(17)) == "down", "a repeat at 12 hours"
    assert decide(True, [first, c(17, DOWN + "again")], n(20)) is None, "the 12 hours run from the latest down comment"
    assert decide(True, [first, c(6, "Daily status"), c(7, "**Watchdog: down.** x")], n(8)) is None, "other comments are ignored"
    assert decide(False, [first], n(18)) == "up"
    assert decide(False, [first, c(18, UP + "ok")], n(19)) is None, "recovery is posted once"
    assert decide(False, [], n(19)) is None and decide(False, [c(1, "Daily status")], n(19)) is None
    assert decide(True, [first, c(18, UP + "ok")], n(19)) == "down", "a new outage posts again"
    # the bodies
    body = down_body(n(4, 24), t(20, 48))
    assert body.startswith(DOWN) and "Down since 28 Oct 20:48 UTC" in body and "55.6 hours lost so far" in body, body
    up = up_body([first], [n(6, 0), n(5, 30), t(20, 48)])
    assert up.startswith(UP) and "Down from 28 Oct 20:48 UTC to 31 Oct 05:30 UTC: 56.7 hours lost" in up, up
    assert "newest" in up_body([(n(1), DOWN + "no marker")], [n(6)])
    # a busy issue: 650 other comments around ours, in pages of 100, oldest first. Only the paging finds the latest down line.
    iso = lambda k: (dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc) + dt.timedelta(hours=k)).isoformat()
    thread = [{"createdAt": iso(k), "body": "Daily status %d" % k} for k in range(650)]
    thread[100] = {"createdAt": iso(100), "body": down_body(n(5), t(20, 48))}
    thread[640] = {"createdAt": iso(640), "body": DOWN + "repeat <!-- since:%s -->" % t(20, 48).isoformat()}
    calls = []

    def page(cursor):
        start = int(cursor or 0)
        calls.append(start)
        chunk = thread[start:start + 100]
        more = start + 100 < len(thread)
        return {"nodes": chunk, "pageInfo": {"hasNextPage": more, "endCursor": str(start + 100) if more else None}}

    got = all_comments(page)
    assert len(got) == 650 and calls == [0, 100, 200, 300, 400, 500, 600], calls
    assert decide(True, got, parse(iso(641))) is None, "the 640th comment is seen, so no repeat an hour later"
    assert decide(True, got, parse(iso(652))) == "down", "and the repeat comes 12 hours after it"
    assert decide(False, got, parse(iso(700))) == "up", "the recovery is posted, not lost"
    first_250 = [(parse(c["createdAt"]), c["body"]) for c in thread[:250]]
    assert decide(True, first_250, parse(iso(641))) == "down", "what reading only 250 comments would have done: a repeat every check"
    try:
        all_comments(lambda cur: {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "x"}})
        raise AssertionError("an endless issue must fail loud")
    except RuntimeError:
        pass
    print("check_collector_health self-test: ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    now = dt.datetime.now(dt.timezone.utc)
    try:
        samples = fetch_sample_times()
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, KeyError) as e:
        print("  [error] could not read the commits on main, so collection health is not known: %s" % e, file=sys.stderr)
        return 2
    down, last, line = verdict(now, samples)
    print(line)
    if "--post" in argv:
        post(now, down, last, samples)
        return 0
    return 1 if down else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
