#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/.build/JARVIS KWS Candidate.app"
MODEL="$APP/Contents/Resources/KWSModel"
if [[ ! -x "$APP/Contents/MacOS/JarvisKWS" ]]; then
  print -u2 "请先运行：python3 scripts/setup_kws_model.py && python3 scripts/build_kws_helper.py"
  exit 1
fi
export JARVIS_KWS_MODEL_DIR="$MODEL"
export JARVIS_KWS_KEYWORDS="$MODEL/jarvis-keywords.txt"
exec "$APP/Contents/MacOS/JarvisKWS"
