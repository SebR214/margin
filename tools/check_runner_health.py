#!/usr/bin/env python3
"""Is the builder alive? No model call. Exit 1 if not.

The builder is the first workflow in BUILDERS that is switched on in GitHub and has a
schedule on main. If none is (all are off or run by hand only, as since 5 Nov 2026), there
is nothing to watch and the check passes. It used to watch aider_builder.yml by name, so
taking that builder off its schedule set off a DOWN email every 30 minutes from 6 Nov.

Down means either:
- no completed run of one_call.yml in the last 26 hours (the runner builds once a day, with backup slots), or
- the last 3 completed runs all failed.

A new workflow gets a 26-hour grace period from its first run being possible:
if it has never completed a run and was added less than 26 hours ago, it is
not down yet.

Env: GH_TOKEN, GITHUB_REPOSITORY.
"""
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

BUILDERS = ["claude_builder.yml", "aider_builder.yml", "one_call.yml"]
SILENT_AFTER = datetime.timedelta(hours=26)


def get(path):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s" % (os.environ["GITHUB_REPOSITORY"], path),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def has_schedule(text):
    return re.search(r"^\s+schedule:", text, re.M) is not None


def scheduled_builder():
    for name in BUILDERS:
        try:
            wf = get("actions/workflows/%s" % name)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        if wf.get("state") != "active":
            continue
        f = get("contents/.github/workflows/%s?ref=main" % name)
        if has_schedule(base64.b64decode(f["content"]).decode()):
            return name, wf
    return None, None


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    WORKFLOW, wf = scheduled_builder()
    if WORKFLOW is None:
        print("no builder is switched on with a schedule, nothing to watch")
        return 0
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
    print("runner alive (%s): last run %d minutes ago, %s" % (WORKFLOW, mins, runs[0]["conclusion"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
