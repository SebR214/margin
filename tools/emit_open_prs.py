#!/usr/bin/env python3
"""Writes data/open_prs_latest.json: how many pull requests are open right now.

M1 (SEB-58) left "pull requests opened" out of the machine room's live SSE
stream on purpose -- knowing a PR is open needs the GitHub API, and handing
that credential to the public-facing stream process was judged a bigger hole
than the gap it would close (see SEB-73). Its own text left this for M2 to
source "another way (a periodic sidecar, not this stream)" -- this is that
sidecar: a short-lived `gh` call, run on a schedule outside any request path,
writing one small file the machine room page reads like any other file in
data/.

Reads GH_TOKEN from the environment -- minted the same isolated way every
other role's gh call already is (agents/gh_token.sh via agents/emit_open_prs.sh),
never a stored personal login. This script does not mint its own token and
does not touch GH_CONFIG_DIR; that is the caller's job.

Exit non-zero and leave any existing file alone on failure: a stale "as of"
timestamp is a visible gap the page can show; a silently overwritten wrong
count is not.

Stdlib only. Usage: python3 tools/emit_open_prs.py
"""

import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "data", "open_prs_latest.json")
REPO = "SebR214/margin"


def main():
    r = subprocess.run(
        ["gh", "pr", "list", "--repo", REPO, "--state", "open", "--json", "number"],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("gh pr list failed: %s" % r.stderr.strip()[:300], file=sys.stderr)
        return 1
    try:
        prs = json.loads(r.stdout)
    except ValueError as e:
        print("gh pr list returned unparseable JSON: %s" % e, file=sys.stderr)
        return 1
    payload = {
        "as_of_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "open_prs": len(prs),
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")
    print("  open PRs         %d" % payload["open_prs"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
