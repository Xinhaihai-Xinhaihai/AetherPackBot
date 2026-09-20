#!/usr/bin/env bash
# Linux-only native boot. Prefer deploy/linux-native.sh for first install.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Cloud native path is Linux. Windows local deploy uses AetherPackBot.exe."
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip
pip install .
exec python main.py
