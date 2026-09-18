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
export ROLE  # so `linear.py state` (SEB-58) can stamp who made the transition

# Each role gets its OWN checkout. Three agents sharing one working tree race on
# .git/FETCH_HEAD -- three simultaneous `git pull` calls produced
# "fatal: Cannot rebase onto multiple branches" on the very first pass -- and it
# is worse than that: the reviewer runs `gh pr checkout` to inspect a branch
# while the builder runs `git checkout -b` for a different one, in the same
# directory. Separate clones make each loop's branch state its own business.
REPO="/srv/margin-$ROLE"

# Every role pushes with the same credential, so GitHub records Sebastian as the
# pusher whatever happens. The commit AUTHOR is ours to set, and setting it is
# the difference between `git log` saying who wrote a change and `git log`
# claiming he wrote all of it (SEB-51). Set per clone, every pass, so it
# survives a re-clone.
git -C "$REPO" config user.name  "margin-$ROLE" 2>/dev/null || true
git -C "$REPO" config user.email "$ROLE@margin.wiki" 2>/dev/null || true

LOGDIR=/var/log/margin
LOG="$LOGDIR/$ROLE.log"
JSONL="$LOGDIR/$ROLE.jsonl"

# How long to wait after a pass that did some work and ended cleanly.
case "$ROLE" in
  builder|reviewer) IDLE=60 ;;
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
# Still used when a MODEL pass returns almost immediately -- that means the
# agent disagreed with the guard about there being work, which is worth slowing
# down on, unlike an honest empty queue.
# A loop whose work signature never changes still wakes the model every
# IDLE_MAX seconds, forever. At 1800 that was 48 paid sessions a day per role
# -- 144 across the three -- spent re-reading a world that had not moved. On
# 2026-09-17 the builder alone woke 161 times and shipped a handful of merges.
# Three hours is still well inside the latency that matters here: work arrives
# when Sebastian queues an issue, and nothing downstream is urgent to the hour.
IDLE_MAX=10800
IDLE_SECONDS=45        # a pass shorter than this did nothing
idle_streak=0
quiet_polls=0
ERROR_WAIT=300          # something went wrong that is not a usage limit

# The backoff above is a heuristic, and heuristics fail open: every previous
# cost incident here was the guard becoming convinced there was work when there
# was not. So the backoff is not the only thing standing between a logic bug
# and the whole subscription. This is a hard ceiling on paid sessions per role
# per UTC day. It cannot be reasoned around, it survives restarts, and when it
# is reached the loop says so plainly and waits for the date to roll over.
# The numbers are deliberately well above a normal day's real work and far
# below what the loops actually spent before it existed.
case "$ROLE" in
  builder)  MAX_WAKES_PER_DAY="${MARGIN_MAX_WAKES:-40}" ;;
  reviewer) MAX_WAKES_PER_DAY="${MARGIN_MAX_WAKES:-30}" ;;
  product)  MAX_WAKES_PER_DAY="${MARGIN_MAX_WAKES:-6}" ;;
esac
WAKES_FILE="$LOGDIR/$ROLE.wakes"

# "<utc-date> <count>". A new date resets the count; an unreadable or corrupt
# file is treated as a fresh day rather than as a reason to stop working.
wakes_today() {
  local d n today
  today=$(date -u +%Y-%m-%d)
  # Guard on readability first: redirecting from a missing file reports the
  # failure before the redirect is suppressed, which would put a spurious
  # error in the log on the first pass of every day.
  [ -r "$WAKES_FILE" ] || { echo 0; return; }
  read -r d n <"$WAKES_FILE" 2>/dev/null || { echo 0; return; }
  # A different date, a missing count, or anything non-numeric means today has
  # no recorded wakes yet. Erring toward 0 lets the loop work; the ceiling is
  # the backstop, not the file's integrity.
  case "$n" in
    ''|*[!0-9]*) echo 0; return ;;
  esac
  if [ "$d" = "$today" ]; then echo "$n"; else echo 0; fi
}

bump_wakes() {
  local today n
  today=$(date -u +%Y-%m-%d)
  n=$(wakes_today)
  printf '%s %s\n' "$today" "$((n + 1))" >"$WAKES_FILE"
}

# Seconds until the next UTC midnight, when the ceiling resets.
until_utc_midnight() {
  local now end
  now=$(date -u +%s)
  end=$(date -u -d "tomorrow 00:00" +%s 2>/dev/null) || end=$((now + 3600))
  echo $((end - now))
}
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

# Is there anything to do? One HTTP request, no model call. Defined as a
# function because the backoff below has to ask the same question while it
# waits -- a loop that sleeps through newly arrived work is the same latency
# bug as a loop that never wakes.
#
# Also sets WORK_SIG as a side effect: a string describing the
# buildable/reviewable world as Linear and GitHub see it right now. Calling
# this before and after a pass and comparing the two strings tells you
# whether the pass changed anything observable -- used below to catch a pass
# that ran long, read a spec, and posted a comment restating a block nothing
# resolved (SEB-71).
have_work_now() {
  case "$ROLE" in
    builder)
      _next=$(python3 "$REPO/agents/linear.py" next 2>/dev/null)
      _stranded=$(python3 "$REPO/agents/linear.py" stranded 2>/dev/null)
      WORK_SIG="$_next|$_stranded"
      [ "$_next" = "NOTHING TO DO" ] && [ "$_stranded" = "NONE STRANDED" ] && return 1
      return 0
      ;;
    reviewer)
      _pending=$(python3 "$REPO/agents/reviewer_work.py" 2>/dev/null)
      WORK_SIG="$_pending"
      [ -z "$_pending" ] && return 1
      return 0
      ;;
  esac
  WORK_SIG=""
  return 0
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
    git -C "$REPO" config user.name  "margin-$ROLE"
    git -C "$REPO" config user.email "$ROLE@margin.wiki"
  fi
  cd "$REPO" || { say "[$ROLE] $REPO is missing"; sleep "$ERROR_WAIT"; continue; }

  # Act as the margin-agents GitHub App, not as Sebastian. Until this existed
  # every role authenticated as his account, so `git log` credited him with
  # every commit and `gh pr review` refused outright -- the reviewer was the
  # author of the PR it was reviewing, which is why every verdict on this repo
  # carries "request-changes not available" (SEB-51).
  #
  # gh and the git credential helper both honour GH_TOKEN over the stored
  # login, so exporting it is the whole switch. Tokens last an hour, so this
  # has to run inside the loop and mint a fresh one every pass, never written
  # to disk -- minting it once before the loop (the previous shape of this
  # code) left every pass after the first hour running on an expired token.
  # have_work_now() below calls gh for the reviewer role and swallows its
  # errors (2>/dev/null) to keep a broken check from stopping the machine, so
  # an expired token didn't fail loud: it just made every pass conclude there
  # was nothing to review, silently, for as long as the service stayed up
  # (SEB-69 -- the reviewer went dark for 13+ hours this way).
  #
  # `gh` must never be able to fall back to a personal login. It resolves
  # credentials in order: the GH_TOKEN env var, then whatever `gh auth login`
  # has stored on this machine. Pointing GH_CONFIG_DIR at a directory that
  # never holds a stored login means a failed mint makes gh fail LOUDLY (no
  # credential found) instead of silently acting as whoever is logged in.
  #
  # This was not hypothetical. Root had a `gh auth login` session for
  # Sebastian's own GitHub account, left over from before this App existed.
  # On 2026-09-17 a single failed mint fell through to it, and `gh` posted a
  # PR comment under his real, write-scoped GitHub login -- not a
  # misattributed git-commit-author field (SEB-64's shape), an actual account
  # session (SEB-73). That stored login has been revoked, but the code must
  # not depend on nobody ever running `gh auth login` on this box again.
  export GH_CONFIG_DIR="/tmp/margin-gh-config-$ROLE"
  mkdir -p "$GH_CONFIG_DIR"

  # If minting fails the pass still runs -- a broken credential must not
  # silently stop the machine -- but every gh call this pass makes will now
  # fail loudly with "no credential found" rather than quietly using
  # something else. The cost of being wrong that way is one wasted pass; the
  # opposite cost, before today, was Sebastian's own GitHub account narrating
  # agent work without his knowledge.
  if [ -n "${MARGIN_GH_APP_ID:-}" ]; then
    if GH_TOKEN="$("$REPO/agents/gh_token.sh" 2>/dev/null)"; then
      export GH_TOKEN
    else
      unset GH_TOKEN
      say "[$ROLE] could not mint a GitHub App token; gh calls this pass fail loudly (isolated GH_CONFIG_DIR, no stored login available)"
    fi
  fi

  # A pass that died mid-review leaves the checkout on a PR branch with the
  # files that pass regenerated still dirty. `git checkout main` then ABORTS --
  # and the `|| true` this line used to carry swallowed it, so the loop stayed
  # on the branch and every later pass died the same way, silently.
  #
  # On 2026-09-16 the reviewer sat wedged exactly like that, 52 regenerated
  # country pages dirty on seb-61-one-chart-component, and not one verdict
  # reached a pull request until a person went looking for why.
  #
  # So: discard tracked modifications first, then switch. Real work lives on
  # branches and is committed before a pass ends, so nothing of value is in the
  # working tree at the top of a pass -- that includes the files a tool
  # regenerates every run and that CI rewrites every hour.
  git rebase --abort >/dev/null 2>&1 || true
  git checkout -- . >/dev/null 2>&1 || true
  git checkout -q main 2>>"$LOG" || true

  # Then check it worked. A loop that cannot reach main cannot do anything
  # useful, and must say so rather than running a pass that is guaranteed to
  # fail.
  if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" != "main" ]; then
    say "[$ROLE] not on main after checkout; resetting hard"
    git reset -q --hard >>"$LOG" 2>&1 || true
    git clean -qfd >>"$LOG" 2>&1 || true
    git checkout -q main 2>>"$LOG" || true
  fi
  if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" != "main" ]; then
    say "[$ROLE] cannot return to main -- this clone needs a person"
    record 0 "cannot reach main" "$(( $(date +%s) - START ))"
    sleep "$ERROR_WAIT"; continue
  fi

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
  have_work_now || HAVE_WORK=0
  SIG_BEFORE="$WORK_SIG"

  if [ "$HAVE_WORK" = "0" ]; then
    # No backoff here, deliberately. The check above is one HTTP request and no
    # model call, so polling frequently costs approximately nothing -- and
    # backing off would trade latency against a cost that no longer exists.
    # Cheap polling can afford to be frequent, so work gets picked up within a
    # minute instead of up to half an hour.
    # A separate counter from idle_streak, which governs how long to wait
    # after a MODEL pass came back empty. Cheap polls must not inflate that --
    # thirty free checks finding nothing is not evidence the model should be
    # rationed, and letting them share a counter sent the next model backoff
    # straight to its ceiling.
    quiet_polls=$((quiet_polls + 1))
    if [ $((quiet_polls % 30)) -eq 1 ]; then
      say "[$ROLE] nothing to do (no model call); polling every ${IDLE}s"
    fi
    sleep "$IDLE"
    continue
  fi

  # ---- Hard daily ceiling, checked after the work guard and before paying. ----
  WAKES=$(wakes_today)
  if [ "$WAKES" -ge "$MAX_WAKES_PER_DAY" ]; then
    SLEEP_FOR=$(until_utc_midnight)
    say "[$ROLE] daily ceiling reached: $WAKES/$MAX_WAKES_PER_DAY model sessions today; there IS work queued, but this loop is done paying until the UTC date rolls over in ${SLEEP_FOR}s"
    record 0 "daily ceiling" 0
    sleep "$SLEEP_FOR"
    continue
  fi
  bump_wakes

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
  #
  # The org's monthly spend cap is a different message with no epoch in it --
  # "You've hit your org's monthly spend limit ... claude.ai/settings/usage" --
  # and until SEB-72 it matched neither 'rate limit' nor 'usage limit', so it
  # fell through to the generic-error branch below and retried every
  # ERROR_WAIT (300s) for hours at a stretch (measured: 235 hits across three
  # multi-hour blackouts, 2026-09-14 through 09-17). It has no reset time to
  # read, so it takes the same LIMIT_FALLBACK wait a usage limit gets when it
  # can't read one either.
  RESET=$(grep -oE 'usage limit reached\|[0-9]+' "$OUT" 2>/dev/null | head -1 | cut -d'|' -f2 || true)
  if [ -n "$RESET" ] || grep -qiE 'rate.?limit|usage limit|spend limit' "$OUT" 2>/dev/null; then
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

  # A pass that ran long is not the same as a pass that did something. SEB-71:
  # the builder spent 4h20m across 62 passes reaching the same "blocked on R2"
  # conclusion for SEB-58/SEB-59, one paid session at a time. Reading the spec,
  # checking SEB-57's state and posting a comment via `linear.py say` reliably
  # took longer than IDLE_SECONDS, so the elapsed-time check below never saw
  # those passes as idle and the backoff never grew past the base IDLE.
  # Comparing the buildable/reviewable world before and after the pass catches
  # that: if `next`/`stranded` (or the reviewer's pending list) come back
  # identical, nothing observable moved, whatever the pass spent its turns on
  # -- restating an unchanged block counts as idle here, same as a fast no-op.
  have_work_now >/dev/null 2>&1
  SIG_AFTER="$WORK_SIG"
  if [ "$ELAPSED" -lt "$IDLE_SECONDS" ] || \
     { [ -n "$SIG_BEFORE" ] && [ "$SIG_BEFORE" = "$SIG_AFTER" ]; }; then
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

  # Wait out the backoff, but keep asking. The backoff exists to stop the model
  # being woken over and over for an empty queue -- it was never meant to make
  # the loop deaf to work that arrives while it waits.
  #
  # On 2026-09-16 the builder backed off to half an hour after five empty
  # passes, U6 went back into Todo ninety seconds later, and it slept through
  # the lot. A person had to restart the service to get it moving.
  #
  # The check is one HTTP request and no model call, so asking every IDLE
  # seconds during the wait costs approximately nothing and removes up to half
  # an hour of dead time.
  #
  # "Work arrived" has to mean the signature CHANGED, not merely that
  # have_work_now() is true -- otherwise it means nothing. SEB-78: overnight on
  # 2026-09-17, SEB-67 sat stranded with PR #109 already open (the filter that
  # excludes that case, #116, hadn't shipped yet), so `stranded` returned it on
  # every check, have_work_now() was true on the very first tick of every wait,
  # and the backoff this loop exists to apply got cancelled before it could
  # grow past its first doubling -- idle x1 for a solid hour, 42 passes, all
  # reaching the same conclusion the tick before had already reached. Comparing
  # against the signature captured right after the last pass (SIG_AFTER) means
  # a persistent, unresolved fact keeps waiting instead of resetting the clock.
  waited=0
  WAIT_BASELINE_SIG="$SIG_AFTER"
  while [ "$waited" -lt "$WAIT" ]; do
    sleep "$IDLE"
    waited=$((waited + IDLE))
    if have_work_now && [ "$WORK_SIG" != "$WAIT_BASELINE_SIG" ]; then
      # SEB-86: the reviewer burned its whole daily wake budget in 47 minutes
      # when this comparison flapped on every single recheck, and the log
      # only ever said "work arrived" -- never what the two sides of the
      # comparison actually were. Printing both here is the only way a
      # future flap is diagnosable instead of guessed at.
      say "[$ROLE] work arrived after ${waited}s of a ${WAIT}s wait; going now (signature before=<${WAIT_BASELINE_SIG}> after=<${WORK_SIG}>)"
      idle_streak=0
      break
    fi
  done
done
