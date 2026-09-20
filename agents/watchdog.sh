#!/usr/bin/env bash
# OPS-4: watch the watchers.
#
# Plain bash, no model call, every 30 minutes. It reads the jsonl records the
# loops write and the collector's own output, and raises one alarm when any of
# these is true:
#
#   - a loop has real work waiting and has recorded nothing for 2+ hours
#     (product: 4+, it has no cheap "is there work" check of its own)
#   - collection has missed 2 consecutive passes
#   - more than 2 live model sessions exist for one role
#
# Why it exists: on 2026-09-16 the reviewer sat wedged on a feature branch for
# hours, its clone dirty, every pass dying before it did anything -- and nothing
# noticed, because the only things watching the loops were the loops. The same
# day a backoff slept through newly-arrived work and the product role held the
# queue at zero. Each was found by a person looking, hours late.
#
# It alarms ONCE and then stays quiet for 6 hours. A watchdog that repeats
# itself is a watchdog people mute.
set -uo pipefail

LOGDIR=/var/log/margin
STATE=/var/lib/margin/watchdog.state
QUIET_SECONDS=$((6 * 3600))
SILENT_AFTER=$((2 * 3600))     # builder/reviewer: silent this long, WITH real work waiting, is down
# product has no cheap "is there work" check of its own (agents/run.sh only
# defines one for builder/reviewer) -- it wakes the model every cycle
# regardless, on a backoff capped at IDLE_MAX=10800 there -- so it needs a
# wider flat window instead, sized to clear that cap plus one real pass.
PRODUCT_SILENT_AFTER=$((4 * 3600))
REPO=/srv/margin-product

# SEB-84: role_has_real_work below is a single snapshot. "Silent for N minutes"
# and "real work waiting right now" can both be true without the work having
# been waiting anywhere near N minutes -- a role that has been correctly idle
# for an empty queue the whole time, with a real issue arriving in the last
# minute, looks identical at check time to one that has been stuck the whole
# time. One file per role remembers whether this exact condition also fired
# last check (30 minutes earlier, same cadence as PENDING_DIR's use below) --
# see the loop for how it's used.
PENDING_DIR=/var/lib/margin/watchdog-pending
mkdir -p "$(dirname "$STATE")" "$PENDING_DIR"
now=$(date +%s)

# Still inside the quiet window from a previous alarm? Say nothing.
if [ -f "$STATE" ]; then
  last=$(cat "$STATE" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$QUIET_SECONDS" ]; then exit 0; fi
fi

problems=()

# 1. A loop gone quiet -- but only when that is not what it is supposed to do.
#    SEB-80 raised this on builder AND reviewer in the same alarm, and neither
#    was actually down:
#
#    - builder/reviewer only write a jsonl record when a MODEL pass runs. The
#      cheap poll that decides whether to wake the model (agents/run.sh,
#      have_work_now) costs no model call, so it writes nothing either -- an
#      honestly idle role with an empty queue is silent for as long as the
#      queue stays empty, unbounded by anything, same shape as the ten-hour
#      empty Todo queue on 2026-09-16. Builder's queue was empty; that is why
#      it had recorded nothing.
#    - a role that hits its own daily wake ceiling (agents/run.sh) logs that
#      fact once, truthfully, then sleeps on purpose until the UTC date rolls
#      over -- which can be most of a day, far past this check's window.
#      Reviewer sat at 30/30 wakes and had logged exactly that.
#
#    So: a role whose last record already explains the silence (a logged
#    "daily ceiling") is not a problem. And for builder, whose queue is one
#    `linear.py` call away (same one agents/run.sh itself uses, no new
#    credential needed), only alarm when there is real unstarted or stranded
#    work actually waiting -- silence with an empty queue is correct, not
#    down.
#
#    SEB-95: this script's own EnvironmentFile already loads the GitHub App
#    credential (same /etc/margin/env the reviewer loop reads), so the "no
#    token available here" gap this comment used to describe was stale --
#    the alarm fired on a reviewer that was correctly idle the whole time
#    (PR #125 already reviewed at its head commit, agents/reviewer_work.py
#    genuinely found nothing pending). Mint one the same isolated way
#    agents/run.sh does (SEB-73: a dedicated GH_CONFIG_DIR so a failed mint
#    fails loud instead of quietly picking up a stored login) and ask
#    reviewer_work.py the same question the reviewer loop itself asks. A
#    mint failure can't tell either way, so it falls back to "real work" --
#    the same posture reviewer_work.py's own gh() helper takes.
role_has_real_work() {
  case "$1" in
    builder)
      n=$(python3 "$REPO/agents/linear.py" next 2>/dev/null)
      s=$(python3 "$REPO/agents/linear.py" stranded 2>/dev/null)
      [ "$n" = "NOTHING TO DO" ] && [ "$s" = "NONE STRANDED" ] && return 1
      return 0
      ;;
    reviewer)
      [ -n "${MARGIN_GH_APP_ID:-}" ] || return 0
      export GH_CONFIG_DIR=/tmp/margin-watchdog-gh-config
      mkdir -p "$GH_CONFIG_DIR"
      token=$("$REPO/agents/gh_token.sh" 2>/dev/null) || return 0
      pending=$(GH_TOKEN="$token" python3 "$REPO/agents/reviewer_work.py" 2>/dev/null)
      [ -z "$pending" ] && return 1
      return 0
      ;;
    *)
      return 0
      ;;
  esac
}

for role in builder reviewer product; do
  f="$LOGDIR/$role.jsonl"
  pending_file="$PENDING_DIR/$role"
  if [ ! -s "$f" ]; then
    problems+=("$role has never recorded a pass ($f is missing or empty)")
    continue
  fi
  # `finished_utc` is ISO with a +00:00 offset; date -d parses it directly.
  last_line=$(tail -1 "$f")
  last_iso=$(printf '%s' "$last_line" | sed -n 's/.*"finished_utc": *"\([^"]*\)".*/\1/p')
  last_reason=$(printf '%s' "$last_line" | sed -n 's/.*"reason": *"\([^"]*\)".*/\1/p')
  last_s=$(date -d "$last_iso" +%s 2>/dev/null || echo 0)
  limit=$SILENT_AFTER
  [ "$role" = "product" ] && limit=$PRODUCT_SILENT_AFTER
  if [ "$last_s" = "0" ]; then
    problems+=("$role: cannot read a timestamp from the last line of $f")
  elif [ "$last_reason" = "daily ceiling" ]; then
    : # sleeping on purpose until the UTC date rolls over -- see comment above
  elif [ $((now - last_s)) -gt "$limit" ] && role_has_real_work "$role"; then
    # Only alarm the second time this fires in a row. A role that is actually
    # alive claims newly-arrived work within one poll cycle (well under 30
    # minutes -- see agents/run.sh's have_work_now), so a real outage is still
    # silent-with-work-waiting on the next check too; a one-tick coincidence
    # is not.
    if [ -f "$pending_file" ]; then
      mins=$(( (now - last_s) / 60 ))
      problems+=("$role has recorded nothing for ${mins} minutes -- systemctl restart margin-$role")
    else
      : > "$pending_file"
    fi
    continue
  fi
  rm -f "$pending_file"
done

# 2. Collection missing two consecutive passes. The collector commits a sample
#    every half hour, so two missed passes is a gap of more than 75 minutes.
#
# Fetches before reading: nothing else keeps this checkout's origin/main
# current. /srv/margin has margin-pull.timer fetching it every 5 minutes for
# the API, but this repo's ref only moves when the product role's own loop
# happens to `git pull`, and that loop can sit idle well past 75 minutes with
# no work queued. Without the fetch this step measures the AGENT'S clone, not
# the collector -- on 2026-09-17 this checkout's last pull landed at 08:17,
# so every check after that compared "now" against a sample commit that was
# already stale, and it eventually crossed the threshold and raised a false
# alarm (SEB-76) while collect.yml, checked directly on GitHub Actions, had
# not missed a single run.
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" fetch -q origin main 2>/dev/null
  last_sample=$(git -C "$REPO" log origin/main --format=%ct --grep='^sample ' -1 2>/dev/null || echo 0)
  if [ "${last_sample:-0}" != "0" ] && [ $((now - last_sample)) -gt 4500 ]; then
    mins=$(( (now - last_sample) / 60 ))
    problems+=("collection has not committed a sample for ${mins} minutes -- check the collect.yml run on GitHub Actions")
  fi
fi

# 3. More than two live model sessions for one role. Runaway spend, and the one
#    condition here that is allowed to interrupt Sebastian between briefs.
for role in builder reviewer product; do
  # `pgrep -fc` prints a count AND exits non-zero when nothing matches, so a
  # `|| echo 0` fallback appends a second zero and the comparison below breaks
  # on "0\n0". Count the lines instead; no match prints nothing.
  n=$(pgrep -f "claude -p.*Role: $role" 2>/dev/null | wc -l | tr -d " ")
  if [ "${n:-0}" -gt 2 ]; then
    problems+=("$role has $n live model sessions -- runaway spend, systemctl restart margin-$role")
  fi
done

[ ${#problems[@]} -eq 0 ] && exit 0

body=$'The watchdog found the machine in a state nothing else would have reported.\n\n'
for p in "${problems[@]}"; do body+="- $p"$'\n'; done
body+=$'\nDetected by agents/watchdog.sh, which runs every 30 minutes with no model call.\nIt will now stay silent for 6 hours whatever happens, so this will not repeat.\n'

# The brief is the only channel (OPS-1), so the alarm goes where the brief can
# read it and Sebastian already looks. There is no mail path on this host --
# no mail, sendmail or msmtp, and no SMTP credential in /etc/margin/env -- so
# email is not available to reuse yet. When one exists, send here as well.
if [ -n "${LINEAR_API_KEY:-}" ] && [ -f "$REPO/agents/linear.py" ]; then
  printf '%s' "$body" > /tmp/watchdog-alarm.md
  python3 "$REPO/agents/linear.py" new "Watchdog: the machine is not running as it should" \
      --body-file /tmp/watchdog-alarm.md --label bug --priority 1 --role product >/dev/null 2>&1 \
    && logger -t margin-watchdog "alarm filed to Linear" \
    || logger -t margin-watchdog "could not file to Linear"
  rm -f /tmp/watchdog-alarm.md
fi

printf '%s' "$body" | logger -t margin-watchdog
echo "$now" > "$STATE"
