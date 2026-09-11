#!/usr/bin/env bash
# One agent loop. Runs forever; systemd restarts it if it dies anyway.
#
#   /srv/margin/agents/run.sh builder|reviewer|product
#
# Each pass: bring the checkout up to date, hand the role file to Claude Code,
# log everything, then sleep for a length that depends on how the pass ended.
# A pass that hits a usage limit sleeps until the limit resets rather than
# hammering the API until it does.

set -uo pipefail

ROLE="${1:?usage: run.sh builder|reviewer|product}"
REPO=/srv/margin
LOGDIR=/var/log/margin
LOG="$LOGDIR/$ROLE.log"
JSONL="$LOGDIR/$ROLE.jsonl"

# How long to wait after a pass that did some work and ended cleanly.
case "$ROLE" in
  builder|reviewer) IDLE=120 ;;
  product)          IDLE=14400 ;;
  *) echo "unknown role: $ROLE" >&2; exit 64 ;;
esac
ERROR_WAIT=300          # something went wrong that is not a usage limit
LIMIT_FALLBACK=1800     # usage limit with no reset time we could read

mkdir -p "$LOGDIR"
umask 022

say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

record() {   # record <ok> <reason> <seconds>
  python3 - "$JSONL" "$ROLE" "$1" "$2" "$3" <<'PY'
import datetime, json, sys
path, role, ok, reason, secs = sys.argv[1:6]
with open(path, "a") as f:
    f.write(json.dumps({
        "role": role,
        "finished_utc": datetime.datetime.now(datetime.timezone.utc)
                                .replace(microsecond=0).isoformat(),
        "ok": ok == "1",
        "reason": reason,
        "seconds": float(secs),
    }) + "\n")
PY
}

while true; do
  START=$(date +%s)
  say "[$ROLE] pass starting"

  cd "$REPO" || { say "[$ROLE] $REPO is missing"; sleep "$ERROR_WAIT"; continue; }

  # The collector chain commits to main every half hour, so a rebase is normal.
  # --autostash keeps a half-finished working tree from blocking the pull.
  if ! git pull --rebase --autostash origin main >>"$LOG" 2>&1; then
    say "[$ROLE] git pull failed; leaving the checkout alone and retrying"
    git rebase --abort >>"$LOG" 2>&1 || true
    record 0 "git pull failed" "$(( $(date +%s) - START ))"
    sleep "$ERROR_WAIT"; continue
  fi

  OUT=$(mktemp)
  set +e
  claude -p "$(cat "$REPO/agents/RULES.md" "$REPO/agents/${ROLE^^}.md")" \
      --allowedTools Bash,Read,Edit,Write,Glob,Grep \
      --max-turns 80 \
      --output-format json >"$OUT" 2>>"$LOG"
  CODE=$?
  set -e
  ELAPSED=$(( $(date +%s) - START ))

  cat "$OUT" >>"$LOG"

  # A usage limit is not a failure and must not be retried in a tight loop.
  # Claude Code reports it as "...usage limit reached|<epoch seconds>".
  RESET=$(grep -oE 'usage limit reached\|[0-9]+' "$OUT" 2>/dev/null | head -1 | cut -d'|' -f2)
  if [ -n "$RESET" ] || grep -qiE 'rate.?limit|usage limit' "$OUT" 2>/dev/null; then
    NOW=$(date +%s)
    if [ -n "$RESET" ] && [ "$RESET" -gt "$NOW" ]; then
      WAIT=$(( RESET - NOW + 60 ))
    else
      WAIT=$LIMIT_FALLBACK
    fi
    say "[$ROLE] usage limit; sleeping ${WAIT}s until it resets"
    record 0 "usage limit" "$ELAPSED"
    rm -f "$OUT"; sleep "$WAIT"; continue
  fi

  if [ "$CODE" -ne 0 ]; then
    say "[$ROLE] exited $CODE; retrying in ${ERROR_WAIT}s"
    record 0 "exit $CODE" "$ELAPSED"
    rm -f "$OUT"; sleep "$ERROR_WAIT"; continue
  fi

  say "[$ROLE] pass finished in ${ELAPSED}s; next in ${IDLE}s"
  record 1 "ok" "$ELAPSED"
  rm -f "$OUT"
  sleep "$IDLE"
done
