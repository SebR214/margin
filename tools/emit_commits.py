#!/usr/bin/env python3
"""data/commits_recent.json: the newest commits on main, for the agents list on how-it-was-built.html.

The page used to ask api.github.com for this itself, without logging in, and GitHub refused it (403).
This tool asks once an hour from the collector run, with the run's own token, and stores the answer.
The page reads the stored file.

Schema
    {"as_of_utc": when it was fetched, "source": the URL asked,
     "commits": [{"sha", "html_url", "date", "email", "message"}]}     newest first, up to 100

Real data only: each row is a field of GitHub's own answer, not computed. If GitHub does not answer
(no token, a non-200, or no commits) the tool exits non-zero and leaves the stored file as it was.

Usage: GITHUB_TOKEN=... python3 tools/emit_commits.py [--self-test]
"""

import datetime as dt
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://api.github.com/repos/SebR214/margin/commits?per_page=100"
OUT = os.path.join(HERE, "data", "commits_recent.json")


def who(email):
    """Keep the address only where it names an agent or the collector; a person's own address is stored as "person"
    (the page only needs the kind of author, and a personal address does not belong in a data file)."""
    e = email or ""
    if e.endswith("@margin.wiki") or "margin-agents" in e or e == "actions@github.com" or e.endswith("@users.noreply.github.com"):
        return e
    return "person" if e else ""


def shape(answer):
    rows = []
    for c in answer:
        commit = c["commit"]
        rows.append({"sha": c["sha"], "html_url": c.get("html_url", ""), "date": commit["author"]["date"],
                     "email": who(commit["author"].get("email", "")), "message": commit["message"]})
    if not rows:
        raise ValueError("GitHub returned no commits")
    return rows


def fetch():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    req = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
                                               "User-Agent": "margin-wiki-emit-commits"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError("GitHub answered %s" % r.status)
        return json.load(r)


def main():
    if "--self-test" in sys.argv:
        sample = [{"sha": "a" * 40, "html_url": "u", "commit": {"author": {"date": "2026-10-09T00:00:00Z", "email": "x@y"}, "message": "m"}}]
        assert shape(sample)[0]["message"] == "m"
        try:
            shape([])
        except ValueError:
            print("emit_commits self-test ok")
            return 0
        raise AssertionError("an empty answer must fail")
    rows = shape(fetch())
    doc = {"as_of_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": URL, "commits": rows}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    os.replace(tmp, OUT)
    print("commits_recent.json: %d commits" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
