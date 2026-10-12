#!/usr/bin/env bash
# Keep a workflow running on time without relying on GitHub's cron, which
# fired the one-call runner only twice on the night of 7 Oct instead of every
# 15 minutes. Same idea as collect.yml's chain, kept short.
#
#   .github/actions-next.sh <workflow file> <minutes between runs>
#
# Sleeps until the next slot, then starts the next run, but only if no newer
# run of this workflow is queued or running. The newest run always carries
# the chain, so two chains can't both survive. Cron stays on as the restarter.
set -euo pipefail
WF="$1"; EVERY="$2"
now_m=$((10#$(date -u +%M))); now_s=$((10#$(date -u +%S)))
wait=$(( (EVERY - now_m % EVERY) * 60 - now_s ))
[ "$wait" -lt 30 ] && wait=$((wait + EVERY * 60))
echo "sleeping ${wait}s until the next slot"
sleep "$wait"
newer=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/$WF/runs?per_page=20" \
  --jq "[.workflow_runs[] | select(.id > $GITHUB_RUN_ID) | select(.status != \"completed\")] | length")
if [ "$newer" != "0" ]; then
  echo "a newer run is active, it carries the chain"
  exit 0
fi
gh api -X POST "repos/$GITHUB_REPOSITORY/actions/workflows/$WF/dispatches" -f ref=main
echo "next run started"
