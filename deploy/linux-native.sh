#!/usr/bin/env bash
# Native Linux install for AetherPackBot (Debian/Ubuntu/RHEL/CentOS/Alma/Rocky).
# Usage:
#   sudo bash deploy/linux-native.sh
#   sudo bash deploy/linux-native.sh --systemd
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WANT_SYSTEMD=0
for arg in "$@"; do
  case "$arg" in
    --systemd) WANT_SYSTEMD=1 ;;
  esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is for Linux servers. On Windows use AetherPackBot.exe."
  exit 1
fi

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo bash deploy/linux-native.sh"
    exit 1
  fi
}

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip python3-dev git build-essential
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip python3-devel git gcc gcc-c++ make
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip python3-devel git gcc gcc-c++ make
  else
    echo "Need apt, dnf, or yum."
    exit 1
  fi
}

open_port() {
  if command -v ufw >/dev/null 2>&1; then
    ufw allow 7619/tcp || true
  elif command -v firewall-cmd >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port=7619/tcp || true
    firewall-cmd --reload || true
  fi
}

need_root
install_packages

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

PY_MAJ="$(python3 -c 'import sys; print(sys.version_info.major)')"
PY_MIN="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [[ "${PY_MAJ}" -lt 3 || "${PY_MIN}" -lt 10 ]]; then
  echo "Python 3.10+ required, found $(python3 --version)"
  exit 1
fi

mkdir -p data/config data/logs data/storage data/plugins
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip
pip install .

open_port

if [[ "${WANT_SYSTEMD}" -eq 1 ]]; then
  UNIT=/etc/systemd/system/aetherpackbot.service
  sed "s|/opt/aetherpackbot|${ROOT}|g" "${ROOT}/deploy/aetherpackbot.service" > "${UNIT}"
  if id aetherpack >/dev/null 2>&1; then
    chown -R aetherpack:aetherpack "${ROOT}"
  else
    sed -i '/^User=/d;/^Group=/d' "${UNIT}"
  fi
  systemctl daemon-reload
  systemctl enable --now aetherpackbot
  echo "systemd unit started. dashboard: http://0.0.0.0:7619"
else
  echo "Install done. Start with:"
  echo "  cd ${ROOT}"
  echo "  source .venv/bin/activate"
  echo "  python main.py"
  echo "Dashboard: http://SERVER_IP:7619"
fi
