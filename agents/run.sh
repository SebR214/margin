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

# Each role gets its OWN checkout. Three agents sharing one working tree race on
# .git/FETCH_HEAD -- three simultaneous `git pull` calls produced
# "fatal: Cannot rebase onto multiple branches" on the very first pass -- and it
# is worse than that: the reviewer runs `gh pr checkout` to inspect a branch
# while the builder runs `git checkout -b` for a different one, in the same
# directory. Separate clones make each loop's branch state its own business.
REPO="/srv/margin-$ROLE"
LOGDIR=/var/log/margin
LOG="$LOGDIR/$ROLE.log"
JSONL="$LOGDIR/$ROLE.jsonl"

# How long to wait after a pass that did some work and ended cleanly.
case "$ROLE" in
  builder|reviewer) IDLE=300 ;;
  product)          IDLE=14400 ;;
  *) echo "unknown role: $ROLE" >&2; exit 64 ;;
esac

# A pass that finds nothing still pays for the whole prompt. Over 24 hours the
# builder ran 2,003 passes and 1,933 of them did nothing -- 96% of the cost for
# none of the work. So an idle pass backs off: each consecutive one doubles the
# wait, up to IDLE_MAX, and the first pass that does real work resets it.
#
# Latency is barely affected. Work arrives when Sebastian queues an issue or a
# builder opens a PR, and neither is urgent to the minute; the reviewer picking
# a PR up twenty minutes later costs nothing real.
IDLE_MAX=1800          # never wait longer than half an hour
IDLE_SECONDS=45        # a pass shorter than this did nothing
idle_streak=0
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

  if [ ! -d "$REPO/.git" ]; then
    say "[$ROLE] no checkout at $REPO; cloning"
    rm -rf "$REPO"
    if ! git clone -q https://github.com/SebR214/margin.git "$REPO" >>"$LOG" 2>&1; then
      say "[$ROLE] clone failed"; sleep "$ERROR_WAIT"; continue
    fi
    git -C "$REPO" config user.name "margin-agent"
    git -C "$REPO" config user.email "margin-agent@users.noreply.github.com"
  fi
  cd "$REPO" || { say "[$ROLE] $REPO is missing"; sleep "$ERROR_WAIT"; continue; }

  # A pass that died mid-review can leave the checkout on a PR branch. Start
  # every pass from main so the loop cannot wedge itself.
  git rebase --abort >/dev/null 2>&1 || true
  git checkout -q main 2>>"$LOG" || true

  # Files a tool here regenerates on every run, and that CI also rewrites every
  # hour. Left dirty they collide with the rebase on the very next pass, so
  # they are discarded before pulling rather than stashed and popped into a
  # conflict. Nothing else in the tree is touched: real work lives on branches.
  for f in data/agent_status.json; do
    git checkout -- "$f" 2>/dev/null || true
  done

  # The collector chain commits to main every half hour, so a rebase is normal.
  # --autostash keeps a half-finished working tree from blocking the pull.
  if ! git pull --rebase --autostash origin main >>"$LOG" 2>&1; then
    say "[$ROLE] git pull failed; leaving the checkout alone and retrying"
    git rebase --abort >>"$LOG" 2>&1 || true
    record 0 "git pull failed" "$(( $(date +%s) - START ))"
    sleep "$ERROR_WAIT"; continue
  fi

  # 200 turns, not 80. Ask (SEB-7) hit the 80-turn ceiling after sixteen minutes
  # and exited with error_max_turns having committed nothing, which would have
  # repeated on every pass forever. A truncated pass wastes everything it did,
  # so a limit set too low costs more than one set too high.
  #
  # No `set -e` anywhere in this loop, deliberately. An earlier version turned
  # errexit on after this call, and the very next line is a grep that exits 1
  # when it finds no rate-limit message -- which is the normal case. The script
  # died there on every pass, systemd restarted it 30s later, and the loop
  # cycled without ever recording a run. Failures here are handled explicitly.
  # ---- Is there anything to do? Ask cheaply, before paying for a session. ----
  #
  # An idle pass used to cost a full model session: load the rules and the role
  # file, reason, discover the queue is empty, exit. Measured over 24 hours that
  # was 88% of every pass -- 3,444 of 3,921. This asks Linear and GitHub the same
  # question over plain HTTP for a fraction of a cent, and only wakes the model
  # when the answer is yes.
  #
  # If the check itself fails, RUN THE PASS. A broken check must never be able
  # to silently stop the machine; the worst case is one wasted session, and the
  # alternative is a loop that quietly does nothing for a day.
  HAVE_WORK=1
  case "$ROLE" in
    builder)
      NEXT=$(python3 "$REPO/agents/linear.py" next 2>/dev/null)
      STRANDED=$(python3 "$REPO/agents/linear.py" stranded 2>/dev/null)
      if [ "$NEXT" = "NOTHING TO DO" ] && [ "$STRANDED" = "NONE STRANDED" ]; then
        HAVE_WORK=0
      fi
      ;;
    reviewer)
      # NOT "is any PR open". A PR awaiting Sebastian's approval stays open by
      # design, and counting it as work makes the reviewer re-review the same
      # branch every pass until he answers -- which could be days.
      #
      # Real work is an issue In Review that has not already been reviewed,
      # i.e. one not yet carrying needs-sebastian.
      PENDING=$(python3 "$REPO/agents/linear.py" issues 2>/dev/null | grep "In Review" | grep -vc "needs-sebastian")
      if [ "$PENDING" = "0" ]; then HAVE_WORK=0; fi
      ;;
  esac

  if [ "$HAVE_WORK" = "0" ]; then
    idle_streak=$((idle_streak + 1))
    WAIT=$IDLE
    n=$idle_streak
    while [ "$n" -gt 0 ] && [ "$WAIT" -lt "$IDLE_MAX" ]; do
      WAIT=$((WAIT * 2)); n=$((n - 1))
    done
    [ "$WAIT" -gt "$IDLE_MAX" ] && WAIT=$IDLE_MAX
    say "[$ROLE] nothing to do (checked without the model, x${idle_streak}); next in ${WAIT}s"
    record 1 "idle, no model call" 0
    sleep "$WAIT"
    continue
  fi

  # Sonnet, not the default. These loops are the largest single consumer of the
  # subscription and most of their work is mechanical -- read an issue, follow a
  # spec, run the checks. Override per role with MARGIN_MODEL if one of them
  # ever needs more.
  MODEL="${MARGIN_MODEL:-claude-sonnet-5}"

  OUT=$(mktemp)
  claude -p "$(cat "$REPO/agents/RULES.md" "$REPO/agents/${ROLE^^}.md")" \
      --model "$MODEL" \
      --allowedTools Bash,Read,Edit,Write,Glob,Grep \
      --max-turns 200 \
      --output-format json >"$OUT" 2>>"$LOG"
  CODE=$?
  ELAPSED=$(( $(date +%s) - START ))

  cat "$OUT" >>"$LOG"

  # A usage limit is not a failure and must not be retried in a tight loop.
  # Claude Code reports it as "...usage limit reached|<epoch seconds>".
  RESET=$(grep -oE 'usage limit reached\|[0-9]+' "$OUT" 2>/dev/null | head -1 | cut -d'|' -f2 || true)
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

  if [ "$ELAPSED" -lt "$IDLE_SECONDS" ]; then
    idle_streak=$((idle_streak + 1))
  else
    idle_streak=0
  fi
  WAIT=$IDLE
  n=$idle_streak
  while [ "$n" -gt 0 ] && [ "$WAIT" -lt "$IDLE_MAX" ]; do
    WAIT=$((WAIT * 2)); n=$((n - 1))
  done
  [ "$WAIT" -gt "$IDLE_MAX" ] && WAIT=$IDLE_MAX

  if [ "$idle_streak" -gt 0 ]; then
    say "[$ROLE] pass finished in ${ELAPSED}s (idle x${idle_streak}); next in ${WAIT}s"
  else
    say "[$ROLE] pass finished in ${ELAPSED}s; next in ${WAIT}s"
  fi
  record 1 "ok" "$ELAPSED"
  rm -f "$OUT"
  sleep "$WAIT"
done
