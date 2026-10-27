#!/usr/bin/env python3
"""One email to Seb when collection has been down for 2 hours or more (27 Oct, Seb: holes in the data nobody caught). No model.

The collector watchdog already notices a dead chain, but it only filed Linear issues, which nobody reads. This posts one comment on
the GitHub issue "Collection down", mentioning the repo owner, so GitHub emails him. One comment per outage: the outage is keyed by
the time of the last "sample" commit on main, so the same outage is never sent twice, and a new one is.

    python3 tools/outage_email.py              # post if needed
    python3 tools/outage_email.py --print      # say what it would do
    python3 tools/outage_email.py --self-test

Env: GH_TOKEN (issues: write), GITHUB_REPOSITORY. Run from collector_watchdog.yml after a checkout with history (fetch-depth 200).
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE = "Collection down"
AFTER = dt.timedelta(hours=2)
MARK = re.compile(r"<!-- outage:([0-9T:+\-]+) -->")
SGT = dt.timezone(dt.timedelta(hours=8))


def last_sample(log):
    """Time of the newest 'sample ...' commit in `git log --format='%aI %s'` output, or None."""
    for line in log.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].startswith("sample "):
            return dt.datetime.fromisoformat(parts[0]).astimezone(dt.timezone.utc)
    return None


def decide(now, last, posted_keys):
    """(post?, key). Post when the last sample is 2 hours old or more and this outage was not sent yet."""
    if last is None:
        return False, None
    key = last.strftime("%Y-%m-%dT%H:%M")
    return (now - last >= AFTER and key not in posted_keys), key


def message(now, last, owner, repo, key):
    down = now - last
    h, m = int(down.total_seconds() // 3600), int(down.total_seconds() % 3600 // 60)
    return ("@%s Collection has been down for %dh%02dm. The last hourly sample was at %s UTC (%s SGT). Every hour it stays down is a "
            "hole in the data that can't be filled later.\n\nRuns: https://github.com/%s/actions/workflows/collect.yml\n\n<!-- outage:%s -->"
            % (owner, h, m, last.strftime("%d %b %H:%M"), last.astimezone(SGT).strftime("%d %b %H:%M"), repo, key))


def gh(path, method="GET", data=None):
    cmd = ["gh", "api", "-X", method, "repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path)]
    for k, v in (data or {}).items():
        cmd += ["-f", "%s=%s" % (k, v)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("gh api %s failed: %s" % (path, r.stderr[-300:]))
    return json.loads(r.stdout) if r.stdout.strip() else None


def main(argv):
    if "--self-test" in argv:
        return self_test()
    now = dt.datetime.now(dt.timezone.utc)
    subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=ROOT, capture_output=True)
    log = subprocess.run(["git", "log", "origin/main", "--format=%aI %s", "-n", "300"], cwd=ROOT, capture_output=True, text=True).stdout
    last = last_sample(log)
    repo = os.environ["GITHUB_REPOSITORY"]
    issues = [x for x in gh("issues?state=open&per_page=100") if x["title"] == TITLE and "pull_request" not in x]
    posted = set()
    if issues:
        for c in gh("issues/%d/comments?per_page=100" % issues[0]["number"]) or []:
            posted.update(MARK.findall(c["body"]))
    post, key = decide(now, last, posted)
    print("last sample: %s, post: %s" % (last, post))
    if not post or "--print" in argv:
        return 0
    number = issues[0]["number"] if issues else gh("issues", "POST", {"title": TITLE, "body": "One comment per collection outage of 2 hours or more (tools/outage_email.py)."})["number"]
    gh("issues/%d/comments" % number, "POST", {"body": message(now, last, repo.split("/")[0], repo, key)})
    print("emailed via issue #%d" % number)
    return 0


def self_test():
    log = "2026-10-27T10:05:00+00:00 fix something\n2026-10-27T09:05:12+00:00 sample 2026-10-27T09:05Z\n2026-10-27T08:35:00+00:00 sample x\n"
    last = last_sample(log)
    assert last == dt.datetime(2026, 10, 27, 9, 5, 12, tzinfo=dt.timezone.utc), last
    assert last_sample("2026-10-27T10:05:00+00:00 fix\n") is None
    t = lambda h, m: dt.datetime(2026, 10, 27, h, m, tzinfo=dt.timezone.utc)  # noqa: E731
    assert decide(t(10, 30), last, set()) == (False, "2026-10-27T09:05"), "under 2 hours: quiet"
    assert decide(t(11, 6), last, set()) == (True, "2026-10-27T09:05"), "2 hours: send"
    assert decide(t(14, 0), last, {"2026-10-27T09:05"}) == (False, "2026-10-27T09:05"), "same outage: once"
    assert decide(t(14, 0), None, set()) == (False, None)
    msg = message(t(11, 6), last, "SebR214", "SebR214/margin", "2026-10-27T09:05")
    assert msg.startswith("@SebR214 Collection has been down for 2h00m.") and "27 Oct 17:05 SGT" in msg
    assert MARK.findall(msg) == ["2026-10-27T09:05"]
    print("outage_email self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
