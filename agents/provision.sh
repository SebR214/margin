#!/usr/bin/env bash
# Bring a fresh Ubuntu 24.04 box to the point where the agents can run.
# Run as root on the server:  bash provision.sh
#
# Idempotent: safe to run again after a failure.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

say() { printf '\n=== %s\n' "$*"; }

say "firewall"
ufw allow OpenSSH
ufw --force enable
ufw status verbose

say "unattended upgrades"
apt-get update -qq
apt-get install -y -qq unattended-upgrades apt-listchanges
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
systemctl enable --now unattended-upgrades

say "base packages"
apt-get install -y -qq git python3 python3-pip curl ca-certificates gnupg jq

say "github cli"
if ! command -v gh >/dev/null; then
  mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    >/etc/apt/sources.list.d/github-cli.list
  apt-get update -qq
  apt-get install -y -qq gh
fi
gh --version | head -1

say "node 20"
if ! node --version 2>/dev/null | grep -qE 'v(2[0-9]|[3-9][0-9])'; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi
node --version; npm --version

say "a browser that can run headless"
# Ubuntu 24.04's chromium is a snap shim, which is awkward on a minimal VPS.
# Google Chrome's own .deb is the dependable option; chromium is the fallback.
if ! command -v chromium >/dev/null && ! command -v google-chrome >/dev/null; then
  if curl -fsSL -o /tmp/chrome.deb \
       https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; then
    apt-get install -y -qq /tmp/chrome.deb || apt-get -y -qq -f install
    rm -f /tmp/chrome.deb
  fi
fi
if ! command -v chromium >/dev/null && ! command -v google-chrome >/dev/null; then
  apt-get install -y -qq chromium-browser || snap install chromium
fi
(command -v google-chrome || command -v chromium || command -v chromium-browser) \
  | head -1

say "caddy"
if ! command -v caddy >/dev/null; then
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi
caddy version

say "claude code"
npm install -g @anthropic-ai/claude-code
claude --version || true

say "directories"
install -d -m 755 /srv/margin
install -d -m 700 /etc/margin
install -d -m 755 /var/log/margin

say "done"
echo "next: gh auth login, claude setup-token, then clone into /srv/margin"
