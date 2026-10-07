#!/usr/bin/env python3
"""Is the one-call runner alive? No model call. Exit 1 if not.

Down means either:
- no completed run of one_call.yml in the last 2 hours, or
- the last 3 completed runs all failed.

A new workflow gets a 2-hour grace period from its first run being possible:
if it has never completed a run and was added less than 2 hours ago, it is
not down yet.

Env: GH_TOKEN, GITHUB_REPOSITORY.
"""
import datetime
import json
import os
import sys
import urllib.request

WORKFLOW = "one_call.yml"
SILENT_AFTER = datetime.timedelta(hours=2)


def get(path):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    wf = get("actions/workflows/%s" % WORKFLOW)
    runs = get("actions/workflows/%s/runs?status=completed&branch=main&per_page=5"
               % WORKFLOW)["workflow_runs"]
    if not runs:
        age = now - ts(wf["created_at"])
        if age < SILENT_AFTER:
            print("runner is new (%d min old), no completed run yet" % (age.total_seconds() // 60))
            return 0
        print("DOWN: the runner has never completed a run")
        return 1
    last = ts(runs[0]["updated_at"])
    mins = int((now - last).total_seconds() // 60)
    if now - last > SILENT_AFTER:
        print("DOWN: the runner's last completed run was %d minutes ago: %s"
              % (mins, runs[0]["html_url"]))
        return 1
    if len(runs) >= 3 and all(r["conclusion"] == "failure" for r in runs[:3]):
        print("DOWN: the runner's last 3 runs all failed: %s" % runs[0]["html_url"])
        return 1
    print("runner alive: last run %d minutes ago, %s" % (mins, runs[0]["conclusion"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
