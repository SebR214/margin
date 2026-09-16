#!/usr/bin/env bash
# Mint a GitHub App installation token for the agent loops.
#
# Prints the token on stdout and nothing else, so callers can do:
#
#     GH_TOKEN="$(agents/gh_token.sh)" gh pr list
#
# Why an App and not a personal token: every role used to authenticate as
# Sebastian, so `git log` credited him with every commit, every PR comment read
# as his word, and `gh pr review` refused outright because the reviewer was the
# author of the PR it was reviewing. That is SEB-51, and it is why every
# reviewer verdict on this repo carries the line "request-changes not
# available".
#
# The App cannot cast an approving review that counts for branch protection,
# and that is deliberate: approval stays something only Sebastian can give,
# which is the signal SEB-63's guard needs.
#
# Tokens last an hour. Mint one per pass; do not cache to disk.
set -euo pipefail

: "${MARGIN_GH_APP_ID:?MARGIN_GH_APP_ID is not set -- see /etc/margin/env}"
: "${MARGIN_GH_APP_KEY:?MARGIN_GH_APP_KEY is not set -- see /etc/margin/env}"
: "${MARGIN_GH_INSTALL_ID:?MARGIN_GH_INSTALL_ID is not set -- see /etc/margin/env}"

[ -r "$MARGIN_GH_APP_KEY" ] || { echo "cannot read $MARGIN_GH_APP_KEY" >&2; exit 1; }

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

now=$(date +%s)
# iat backdated 60s: GitHub rejects a JWT whose iat is in the future, and the
# server clock drifting a few seconds ahead of GitHub's is enough to do that.
header='{"alg":"RS256","typ":"JWT"}'
payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$MARGIN_GH_APP_ID")

signing_input="$(printf '%s' "$header" | b64url).$(printf '%s' "$payload" | b64url)"
signature=$(printf '%s' "$signing_input" \
  | openssl dgst -sha256 -sign "$MARGIN_GH_APP_KEY" -binary \
  | b64url)
jwt="$signing_input.$signature"

resp=$(curl -sS -X POST \
  -H "Authorization: Bearer $jwt" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/app/installations/${MARGIN_GH_INSTALL_ID}/access_tokens")

token=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))')

if [ -z "$token" ]; then
  # Print GitHub's message, never the response body wholesale -- it is small,
  # but it is one field away from carrying something that should not be logged.
  msg=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("message","no token and no message"))' 2>/dev/null || echo "unparseable response")
  echo "could not mint an installation token: $msg" >&2
  exit 1
fi

printf '%s' "$token"
