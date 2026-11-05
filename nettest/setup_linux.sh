#!/usr/bin/env bash
# One-time setup on the Linux test laptop (Debian/Ubuntu). Run from the repo root:
#   bash nettest/setup_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== system packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv ffmpeg iproute2 ethtool iputils-ping curl git

echo "== netem kernel module"
if ! sudo modprobe sch_netem; then
  # some Ubuntu kernels ship netem in linux-modules-extra
  sudo apt-get install -y "linux-modules-extra-$(uname -r)"
  sudo modprobe sch_netem
fi

echo "== python (needs 3.11+ for the pinned packages)"
PY=python3
if ! $PY -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  for cand in python3.13 python3.12 python3.11; do
    if command -v $cand >/dev/null; then PY=$cand; break; fi
  done
fi
if ! $PY -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "Python 3.11+ not found. Install one (e.g. 'sudo apt install python3.12 python3.12-venv'"
  echo "or via the deadsnakes PPA on older Ubuntu), then re-run this script."
  exit 1
fi
$PY -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== toxiproxy"
V="${TOXIPROXY_VERSION:-2.9.0}"
ARCH="$(dpkg --print-architecture)"   # amd64 or arm64
mkdir -p nettest/bin
curl -fL -o nettest/bin/toxiproxy-server \
  "https://github.com/Shopify/toxiproxy/releases/download/v${V}/toxiproxy-server-linux-${ARCH}"
chmod +x nettest/bin/toxiproxy-server
nettest/bin/toxiproxy-server -version
sha256sum nettest/bin/toxiproxy-server | tee nettest/bin/toxiproxy-server.sha256

echo "== quick self-test (no root needed)"
.venv/bin/python -m pytest -q tests/test_m4_nettest.py

echo
echo "Setup done. Next:  sudo .venv/bin/python -m nettest.run preflight"
