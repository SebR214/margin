#!/usr/bin/env bash
# The box restarts collection (SEB-436). No model, no cost: curl, openssl and python3, all already on the box.
#
# collect.yml is a chain of GitHub Actions runs, each starting the next. When the chain dies (a cancelled run, a GitHub outage) it
# used to stay dead until a GitHub cron fire, and GitHub drops most of those (4 of 48 landed on 2 Nov). This runs every 10 minutes
# from margin-collect-restarter.timer: if no collect.yml run on main is in progress or queued, it starts one with chain=true.
# A live chain always has a run sleeping for its slot, so on a healthy day this finds one and does nothing. If the cron restarter
# fires at the same moment, tools/collect_chain.py lets exactly one of the two go on. The GitHub cron stays as a second line.
#
# The token comes from agents/gh_token.sh (the margin-agents App, settings in /etc/margin/env). The App needs the repository
# permission Actions: Read and write. Without it GitHub answers 403 here and the script says so; nothing else breaks.
#
#     agents/collect_restarter.sh            # restart the chain if it is dead
#     agents/collect_restarter.sh --check    # only prove the token can read and start runs (the installer does this)
set -euo pipefail

REPO="${MARGIN_REPO:-SebR214/margin}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
api="https://api.github.com/repos/${REPO}/actions/workflows/collect.yml"

token="$(GH_TOKEN_SHOW_PERMISSIONS=1 "$here/gh_token.sh")"
get() { curl -sS --fail-with-body -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" "$1"; }

# runs of collect.yml on main that are going or waiting, not counting a one-shot test run
alive=0
for status in in_progress queued; do
  n="$(get "${api}/runs?status=${status}&branch=main&per_page=100" | python3 -c '
import json, sys
runs = json.load(sys.stdin)["workflow_runs"]
print(sum(1 for r in runs if r.get("display_title") != "collect one-shot"))')"
  alive=$((alive + n))
done

if [ "${1:-}" = "--check" ]; then
  echo "can read the runs of collect.yml: ${alive} live"
  exit 0
fi

if [ "$alive" -gt 0 ]; then
  echo "chain alive: ${alive} run(s) going or queued"
  exit 0
fi

echo "no collect run going or queued: starting the chain"
out="$(mktemp)"
trap 'rm -f "$out"' EXIT
code="$(curl -sS -o "$out" -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
  "${api}/dispatches" -d '{"ref":"main","inputs":{"chain":"true"}}')"
if [ "$code" = "204" ]; then
  echo "started a collect run with chain=true"
  exit 0
fi
msg="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("message", "no message"))' "$out" 2>/dev/null || echo "unreadable answer")"
echo "could not start collection: HTTP ${code}: ${msg}" >&2
[ "$code" = "403" ] && echo "the margin-agents App needs the repository permission Actions: Read and write" >&2
exit 1
