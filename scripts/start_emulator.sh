#!/usr/bin/env bash
# Start the ks_play34 Android emulator (Play Store image).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/env.sh"

AVD_NAME="${AVD_NAME:-ks_play34}"

if adb devices | grep -q 'emulator-.*device'; then
  echo "An emulator is already connected:"
  adb devices -l
  exit 0
fi

echo "Starting AVD: $AVD_NAME"
nohup emulator -avd "$AVD_NAME" -no-metrics -gpu swiftshader_indirect \
  > /tmp/ks-emulator.log 2>&1 &
echo "emulator pid=$! (log: /tmp/ks-emulator.log)"

echo "Waiting for boot..."
adb wait-for-device
for _ in $(seq 1 60); do
  boot="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
  if [[ "$boot" == "1" ]]; then
    adb shell settings put system screen_off_timeout 2147483647 || true
    echo "Booted. Devices:"
    adb devices -l
    exit 0
  fi
  sleep 5
done
echo "Timed out waiting for boot; see /tmp/ks-emulator.log" >&2
exit 1
