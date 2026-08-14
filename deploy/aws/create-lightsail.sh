#!/usr/bin/env bash
# Create a cheap Lightsail Ubuntu instance in eu-west-1 for KS UI.
set -euo pipefail

PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
REGION="${AWS_REGION:-eu-west-1}"
INSTANCE_NAME="${KS_LIGHTSAIL_NAME:-ks-ui}"
# $5/mo tier is safer for Python; override with nano_3_0 if you want cheapest.
BUNDLE_ID="${KS_LIGHTSAIL_BUNDLE:-micro_3_0}"
BLUEPRINT_ID="${KS_LIGHTSAIL_BLUEPRINT:-ubuntu_24_04}"
AZ="${KS_LIGHTSAIL_AZ:-eu-west-1a}"

echo "Region=$REGION name=$INSTANCE_NAME bundle=$BUNDLE_ID blueprint=$BLUEPRINT_ID az=$AZ"

if ! aws lightsail get-bundles --region "$REGION" --query 'bundles[0].bundleId' --output text >/dev/null; then
  echo "ERROR: Lightsail API denied. Attach AmazonLightsailFullAccess to IAM user aaaa137." >&2
  echo "See deploy/aws/IAM-PERMISSIONS.md" >&2
  exit 1
fi

# Prefer an existing key pair; otherwise create one.
KEY_NAME="${KS_LIGHTSAIL_KEY:-ks-ui}"
if ! aws lightsail get-key-pair --region "$REGION" --key-pair-name "$KEY_NAME" >/dev/null 2>&1; then
  echo "Creating Lightsail key pair $KEY_NAME (private key saved under ./deploy/aws/.secrets/ — gitignored)"
  mkdir -p "$(dirname "$0")/.secrets"
  chmod 700 "$(dirname "$0")/.secrets"
  aws lightsail create-key-pair \
    --region "$REGION" \
    --key-pair-name "$KEY_NAME" \
    --query 'privateKeyBase64' \
    --output text | base64 --decode > "$(dirname "$0")/.secrets/${KEY_NAME}.pem"
  chmod 600 "$(dirname "$0")/.secrets/${KEY_NAME}.pem"
fi

if aws lightsail get-instance --region "$REGION" --instance-name "$INSTANCE_NAME" >/dev/null 2>&1; then
  echo "Instance $INSTANCE_NAME already exists"
else
  aws lightsail create-instances \
    --region "$REGION" \
    --instance-names "$INSTANCE_NAME" \
    --availability-zone "$AZ" \
    --blueprint-id "$BLUEPRINT_ID" \
    --bundle-id "$BUNDLE_ID" \
    --key-pair-name "$KEY_NAME"
  echo "Waiting for instance to become running..."
  for _ in $(seq 1 60); do
    state=$(aws lightsail get-instance --region "$REGION" --instance-name "$INSTANCE_NAME" --query 'instance.state.name' --output text)
    echo "  state=$state"
    [[ "$state" == "running" ]] && break
    sleep 5
  done
fi

# Open HTTP/HTTPS (SSH is open by default on Lightsail)
aws lightsail open-instance-public-ports \
  --region "$REGION" \
  --instance-name "$INSTANCE_NAME" \
  --port-info fromPort=80,toPort=80,protocol=tcp \
  >/dev/null || true
aws lightsail open-instance-public-ports \
  --region "$REGION" \
  --instance-name "$INSTANCE_NAME" \
  --port-info fromPort=443,toPort=443,protocol=tcp \
  >/dev/null || true

IP=$(aws lightsail get-instance --region "$REGION" --instance-name "$INSTANCE_NAME" --query 'instance.publicIpAddress' --output text)
echo
echo "Public IP: $IP"
echo "Spaceship DNS: create A record  name=www  value=$IP"
echo "Then: ./deploy/aws/push-and-install.sh $IP"
