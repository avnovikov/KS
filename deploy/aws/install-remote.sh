#!/usr/bin/env bash
# Run ON the Lightsail instance as root (via push-and-install.sh).
set -euo pipefail

DOMAIN="${KS_DOMAIN:-www.aaaa137.fun}"
REPO_URL="${KS_REPO_URL:-https://github.com/avnovikov/KS.git}"
REPO_DIR="${KS_REPO_DIR:-/opt/ks}"
USERS_ROOT="${KS_USERS_ROOT:-/var/lib/ks/users}"
ENV_FILE="${KS_ENV_FILE:-/etc/ks/ks-ui.env}"
SERVICE_USER="${KS_SERVICE_USER:-ks}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl debian-keyring debian-archive-keyring apt-transport-https gnupg

if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home /var/lib/ks --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p /var/lib/ks "$USERS_ROOT" /etc/ks
chown -R "$SERVICE_USER:$SERVICE_USER" /var/lib/ks

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone "$REPO_URL" "$REPO_DIR"
else
  git -C "$REPO_DIR" fetch origin
  git -C "$REPO_DIR" checkout main
  git -C "$REPO_DIR" pull --ff-only origin main
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR"

sudo -u "$SERVICE_USER" bash -lc "
  set -euo pipefail
  cd '$REPO_DIR'
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -U pip
  pip install -e '.[ui]'
"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing $ENV_FILE (push secrets first)" >&2
  exit 1
fi
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

# Ensure public URL matches this host
if ! grep -q '^KS_PUBLIC_BASE_URL=' "$ENV_FILE"; then
  echo "KS_PUBLIC_BASE_URL=https://$DOMAIN" >>"$ENV_FILE"
fi

cat >/etc/systemd/system/ks-ui.service <<EOF
[Unit]
Description=KS Heroes UI (Discord auth)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/ks-heroes ui --auth discord --users-root $USERS_ROOT --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/caddy/Caddyfile <<EOF
$DOMAIN {
	reverse_proxy 127.0.0.1:8000
}
EOF

systemctl daemon-reload
systemctl enable --now caddy
systemctl enable ks-ui.service
systemctl restart ks-ui.service
systemctl reload caddy || systemctl restart caddy

echo "Install complete for https://$DOMAIN"
systemctl --no-pager --full status ks-ui.service | head -25 || true
echo
echo "If Discord login denies everyone: set guild_id in $REPO_DIR/config/auth.yaml and restart ks-ui."
