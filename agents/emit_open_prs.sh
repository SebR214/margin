#!/usr/bin/env bash
# Runs tools/emit_open_prs.py on a schedule, for the machine room's "open
# pull requests" meter (SEB-59, M2).
#
# Mints its own short-lived GitHub App token the same isolated way every
# agent loop already does (see agents/run.sh and agents/gh_token.sh): a
# GH_CONFIG_DIR that never holds a stored personal login, so a failed mint
# makes `gh` fail loudly instead of silently falling back to whoever is
# logged in on this box. That fallback is exactly what happened on
# 2026-09-17 (SEB-73) -- this script must not reintroduce it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export GH_CONFIG_DIR="/tmp/margin-gh-config-open-prs"
mkdir -p "$GH_CONFIG_DIR"

if GH_TOKEN="$(agents/gh_token.sh)"; then
  export GH_TOKEN
else
  unset GH_TOKEN
  echo "could not mint a GitHub App token; gh calls this pass fail loudly (isolated GH_CONFIG_DIR, no stored login available)" >&2
fi

python3 tools/emit_open_prs.py
