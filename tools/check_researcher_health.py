#!/usr/bin/env python3
"""Has the researcher run? No model call. Exit 1 if there is no successful run of
researcher.yml in the last 8 days (SEB-301). A new workflow gets 8 days of grace
from its creation.

Env: GH_TOKEN, GITHUB_REPOSITORY.
"""
import datetime
import json
import os
import sys
import urllib.request

WORKFLOW = "researcher.yml"
SILENT_AFTER = datetime.timedelta(days=8)


def get(path):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def verdict(now, created_at, runs):
    """(ok, message) from the workflow's creation time and its completed runs, newest first."""
    good = [r for r in runs if r["conclusion"] == "success"]
    if good:
        age = now - ts(good[0]["updated_at"])
        if age > SILENT_AFTER:
            return False, "DOWN: the researcher's last successful run was %d days ago: %s" % (age.days, good[0]["html_url"])
        return True, "researcher alive: last successful run %d hours ago" % (age.total_seconds() // 3600)
    if now - ts(created_at) < SILENT_AFTER:
        return True, "researcher is new (%d days old), no successful run yet" % (now - ts(created_at)).days
    return False, "DOWN: the researcher has no successful run in 8 days"


def self_test():
    now = datetime.datetime(2026, 10, 20, tzinfo=datetime.timezone.utc)
    ok = {"conclusion": "success", "updated_at": "2026-10-14T01:05:00Z", "html_url": "u"}
    old = {"conclusion": "success", "updated_at": "2026-10-05T01:05:00Z", "html_url": "u"}
    bad = {"conclusion": "failure", "updated_at": "2026-10-19T01:05:00Z", "html_url": "u"}
    assert verdict(now, "2026-09-01T00:00:00Z", [ok])[0]
    assert not verdict(now, "2026-09-01T00:00:00Z", [bad, old])[0]
    assert not verdict(now, "2026-09-01T00:00:00Z", [])[0]
    assert verdict(now, "2026-10-15T00:00:00Z", [])[0]
    assert verdict(now, "2026-09-01T00:00:00Z", [bad, ok])[0]
    print("check_researcher_health self-test: ok")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    wf = get("actions/workflows/%s" % WORKFLOW)
    runs = get("actions/workflows/%s/runs?status=completed&per_page=20" % WORKFLOW)["workflow_runs"]
    ok, msg = verdict(now, wf["created_at"], runs)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
