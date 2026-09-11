#!/usr/bin/env bash
# Install and start the three agent loops. Run as root on the server, from a
# checkout at /srv/margin:  bash agents/install.sh
set -euo pipefail

REPO=/srv/margin
test -f "$REPO/agents/run.sh" || { echo "run from a checkout at $REPO"; exit 1; }
test -s /etc/margin/env || { echo "/etc/margin/env is missing or empty"; exit 1; }

# One checkout per role. run.sh clones its own if missing, but doing it here
# means the first pass starts with work rather than with a clone.
for role in builder reviewer product; do
  if [ ! -d "/srv/margin-$role/.git" ]; then
    echo "cloning /srv/margin-$role"
    git clone -q https://github.com/SebR214/margin.git "/srv/margin-$role"
    git -C "/srv/margin-$role" config user.name "margin-agent"
    git -C "/srv/margin-$role" config user.email "margin-agent@users.noreply.github.com"
  fi
done

chmod +x "$REPO/agents/run.sh"
install -d -m 755 /var/log/margin
install -m 644 "$REPO"/agents/systemd/margin-*.service /etc/systemd/system/
systemctl daemon-reload

for role in builder reviewer product; do
  systemctl enable "margin-$role"
  systemctl restart "margin-$role"
done

sleep 3
systemctl --no-pager --lines=3 status margin-builder margin-reviewer margin-product || true
