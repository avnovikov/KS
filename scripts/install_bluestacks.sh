#!/usr/bin/env bash
# Install BlueStacks from the pre-downloaded pkg (requires one admin password).
set -euo pipefail
PKG="${1:-$HOME/Downloads/BlueStacksInstaller.pkg}"
if [[ ! -f "$PKG" ]]; then
  echo "Missing installer: $PKG" >&2
  echo "Re-download with: brew fetch --cask bluestacks" >&2
  exit 1
fi
echo "Installing BlueStacks from $PKG (sudo password required once)..."
sudo installer -pkg "$PKG" -target /
echo "Done. Launch BlueStacks from Applications, enable ADB, then:"
echo "  adb connect 127.0.0.1:<port-from-bluestacks-settings>"
