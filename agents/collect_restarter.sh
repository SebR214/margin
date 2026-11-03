#!/usr/bin/env bash
# The box restarts collection (SEB-436). No model, no cost: curl, openssl and python3, all already on the box.
#
# collect.yml is a chain of GitHub Actions runs, each starting the next. When the chain dies (a cancelled run, a GitHub outage) it
# used to stay dead until a GitHub cron fire, and GitHub drops most of those (4 of 48 landed on 2 Nov). This runs every 10 minutes
# from margin-collect-restarter.timer: if no collect.yml run on main is in progress or queued, it starts one as the chain.
# A live chain always has a run sleeping for its slot, so on a healthy day this finds one and does nothing. If the cron restarter
# fires at the same moment, tools/collect_chain.py lets exactly one of the two go on. The GitHub cron stays as a second line.
#
# How it talks to GitHub. The margin-agents App is granted Contents, Pull requests, Workflows, Checks and Metadata, and no Actions
# permission, so it can neither list nor dispatch workflow runs. It does not need to. The list of runs of a public repository is
# readable without a token (60 requests an hour; this uses 24), and the App can send a repository_dispatch, which needs only
# Contents: write. collect.yml starts a chain when that event carries chain=true. The token comes from agents/gh_token.sh
# (settings in /etc/margin/env).
#
#     agents/collect_restarter.sh            # restart the chain if it is dead
#     agents/collect_restarter.sh --check    # prove it can read the runs and send a dispatch (the installer does this)
set -euo pipefail

REPO="${MARGIN_REPO:-SebR214/margin}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
api="https://api.github.com/repos/${REPO}"

# runs of collect.yml on main that are going or waiting, not counting a one-shot test run
alive=0
for status in in_progress queued; do
  url="${api}/actions/workflows/collect.yml/runs?status=${status}&branch=main&per_page=100"
  body="$(curl -sS --fail-with-body -H "Accept: application/vnd.github+json" "$url")" || {
    echo "could not read the runs of collect.yml: ${body}" >&2; exit 1; }
  n="$(printf '%s' "$body" | python3 -c '
import json, sys
runs = json.load(sys.stdin)["workflow_runs"]
print(sum(1 for r in runs if r.get("display_title") != "collect one-shot"))')"
  alive=$((alive + n))
done

# repository_dispatch with an event name no workflow listens to: proves the token may send one, starts nothing
send() {
  local payload="$1" out code msg
  token="$(GH_TOKEN_SHOW_PERMISSIONS=1 "$here/gh_token.sh")"
  out="$(mktemp)"
  code="$(curl -sS -o "$out" -w '%{http_code}' -X POST -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
    "${api}/dispatches" -d "$payload")"
  if [ "$code" = "204" ]; then rm -f "$out"; return 0; fi
  msg="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("message", "no message"))' "$out" 2>/dev/null || echo "unreadable answer")"
  rm -f "$out"
  echo "could not send a dispatch: HTTP ${code}: ${msg}" >&2
  [ "$code" = "403" ] || [ "$code" = "404" ] && echo "the margin-agents App needs the repository permission Contents: Read and write" >&2
  return 1
}

if [ "${1:-}" = "--check" ]; then
  echo "can read the runs of collect.yml: ${alive} live"
  send '{"event_type":"collect_restarter_check"}'
  echo "can send a repository_dispatch"
  exit 0
fi

if [ "$alive" -gt 0 ]; then
  echo "chain alive: ${alive} run(s) going or queued"
  exit 0
fi

echo "no collect run going or queued: starting the chain"
send '{"event_type":"collect","client_payload":{"chain":"true"}}'
echo "sent a repository_dispatch: collect with chain=true"
