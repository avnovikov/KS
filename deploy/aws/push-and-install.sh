#!/usr/bin/env bash
# Copy secrets + install script to a Lightsail host and run install as root.
set -euo pipefail

PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
IP="${1:?Usage: $0 <PUBLIC_IP>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SECRETS_FILE="${KS_SECRETS_FILE:-$REPO_ROOT/../../deploy-secrets/ks-ui.env}"
# When run from worktree, prefer monorepo-adjacent secrets:
if [[ ! -f "$SECRETS_FILE" ]]; then
  SECRETS_FILE="/Users/alexei/KS/deploy-secrets/ks-ui.env"
fi
KEY_PATH="${KS_SSH_KEY:-$SCRIPT_DIR/.secrets/ks-ui.pem}"
SSH_USER="${KS_SSH_USER:-ubuntu}"

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Missing secrets file: $SECRETS_FILE" >&2
  echo "Create it with DISCORD_* and KS_* vars (see deploy/aws/README.md)." >&2
  exit 1
fi
if grep -q 'REPLACE' "$SECRETS_FILE"; then
  echo "Secrets file still has REPLACE placeholders: $SECRETS_FILE" >&2
  echo "Fill DISCORD_OAUTH_CLIENT_ID/SECRET and DISCORD_BOT_TOKEN first." >&2
  exit 1
fi
if [[ ! -f "$KEY_PATH" ]]; then
  echo "Missing SSH key: $KEY_PATH (run create-lightsail.sh first)" >&2
  exit 1
fi

echo "Waiting for SSH on $IP..."
for _ in $(seq 1 36); do
  if ssh -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
    "$SSH_USER@$IP" 'echo ok' >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

scp -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new \
  "$SECRETS_FILE" "$SSH_USER@$IP:/tmp/ks-ui.env"
scp -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new \
  "$SCRIPT_DIR/install-remote.sh" "$SSH_USER@$IP:/tmp/install-remote.sh"

ssh -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new "$SSH_USER@$IP" bash -s <<EOF
set -euo pipefail
sudo mkdir -p /etc/ks
sudo mv /tmp/ks-ui.env /etc/ks/ks-ui.env
sudo chmod 600 /etc/ks/ks-ui.env
sudo bash /tmp/install-remote.sh
EOF

echo "Done. Open https://www.aaaa137.fun after DNS A www -> $IP propagates."
