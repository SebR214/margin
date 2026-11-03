#!/usr/bin/env bash
# Install the collection restarter on the box (SEB-436). Run once as root, from the checkout the box keeps current:
#
#     sudo bash /srv/margin/agents/install_restarter.sh
#
# It proves the App token works before it turns anything on, installs the service and the timer, and runs the service once.
set -euo pipefail
REPO=/srv/margin
[ "$(id -u)" = 0 ] || { echo "run as root: sudo bash $0" >&2; exit 1; }
test -s /etc/margin/env || { echo "/etc/margin/env is missing or empty" >&2; exit 1; }
test -f "$REPO/agents/collect_restarter.sh" || { echo "$REPO/agents/collect_restarter.sh is not there yet; margin-pull.timer refreshes $REPO from main every 5 minutes" >&2; exit 1; }

chmod +x "$REPO/agents/collect_restarter.sh" "$REPO/agents/gh_token.sh"
set -a; . /etc/margin/env; set +a
"$REPO/agents/collect_restarter.sh" --check

install -m 644 "$REPO"/agents/systemd/margin-collect-restarter.service /etc/systemd/system/
install -m 644 "$REPO"/agents/systemd/margin-collect-restarter.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now margin-collect-restarter.timer
systemctl start margin-collect-restarter.service
journalctl -u margin-collect-restarter.service -n 12 --no-pager
systemctl list-timers margin-collect-restarter.timer --no-pager
