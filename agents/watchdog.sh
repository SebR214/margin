#!/usr/bin/env bash
# OPS-4: watch the watchers.
#
# Plain bash, no model call, every 30 minutes. It reads the jsonl records the
# loops write and the collector's own output, and raises one alarm when any of
# these is true:
#
#   - a loop has recorded nothing for 2+ hours
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
SILENT_AFTER=$((2 * 3600))     # a loop that has said nothing this long is down
REPO=/srv/margin-product

mkdir -p "$(dirname "$STATE")"
now=$(date +%s)

# Still inside the quiet window from a previous alarm? Say nothing.
if [ -f "$STATE" ]; then
  last=$(cat "$STATE" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$QUIET_SECONDS" ]; then exit 0; fi
fi

problems=()

# 1. A loop that has recorded nothing for two hours.
for role in builder reviewer product; do
  f="$LOGDIR/$role.jsonl"
  if [ ! -s "$f" ]; then
    problems+=("$role has never recorded a pass ($f is missing or empty)")
    continue
  fi
  # `finished_utc` is ISO with a +00:00 offset; date -d parses it directly.
  last_iso=$(tail -1 "$f" | sed -n 's/.*"finished_utc": *"\([^"]*\)".*/\1/p')
  last_s=$(date -d "$last_iso" +%s 2>/dev/null || echo 0)
  if [ "$last_s" = "0" ]; then
    problems+=("$role: cannot read a timestamp from the last line of $f")
  elif [ $((now - last_s)) -gt "$SILENT_AFTER" ]; then
    mins=$(( (now - last_s) / 60 ))
    problems+=("$role has recorded nothing for ${mins} minutes -- systemctl restart margin-$role")
  fi
done

# 2. Collection missing two consecutive passes. The collector commits a sample
#    every half hour, so two missed passes is a gap of more than 75 minutes.
if [ -d "$REPO/.git" ]; then
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
