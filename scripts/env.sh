# Source before ks / adb / emulator work:
#   source /Users/alexei/KS/scripts/env.sh

export JAVA_HOME="${JAVA_HOME:-$HOME/.local/jdk/current}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# Project venv (opencv, pytesseract, ks package)
if [[ -f /Users/alexei/KS/.venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /Users/alexei/KS/.venv/bin/activate
fi

# Panorama OCR (brew install tesseract)
export TESSDATA_PREFIX="${TESSDATA_PREFIX:-/opt/homebrew/share/tessdata}"
