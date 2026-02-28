#!/usr/bin/env bash
set -euo pipefail

WITH_NODE_RED=0
WITH_TENSORFLOW=0
WITH_TFLITE=0
WITH_AUDIO=1
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage: ./scripts/install_rpi.sh [options]

Options:
  --with-node-red     Install Node-RED using official installer script.
  --with-tensorflow   Install TensorFlow in the project venv.
  --with-tflite       Install TensorFlow Lite runtime in the project venv.
  --no-audio          Skip audio/TTS related Python modules.
  -h, --help          Show this help.

Examples:
  ./scripts/install_rpi.sh
  ./scripts/install_rpi.sh --with-node-red --with-tflite
  ./scripts/install_rpi.sh --with-node-red --with-tensorflow
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-node-red)
      WITH_NODE_RED=1
      shift
      ;;
    --with-tensorflow)
      WITH_TENSORFLOW=1
      shift
      ;;
    --with-tflite)
      WITH_TFLITE=1
      shift
      ;;
    --no-audio)
      WITH_AUDIO=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python binary not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "[1/6] Installing system packages..."
${SUDO} apt-get update
${SUDO} apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  build-essential \
  libusb-1.0-0-dev \
  libatlas-base-dev \
  espeak \
  mosquitto \
  mosquitto-clients \
  curl \
  git \
  ca-certificates

echo "[2/6] Enabling MQTT broker..."
${SUDO} systemctl enable --now mosquitto || true

if [[ "${WITH_NODE_RED}" -eq 1 ]]; then
  echo "[3/6] Installing Node-RED..."
  bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered)
  ${SUDO} systemctl enable --now nodered.service || true
else
  echo "[3/6] Node-RED install skipped."
fi

echo "[4/6] Creating virtual environment..."
cd "${PROJECT_ROOT}"
if [[ ! -d ".venv" ]]; then
  "${PYTHON_BIN}" -m venv .venv
fi
source .venv/bin/activate

echo "[5/6] Installing Python modules..."
pip install --upgrade pip setuptools wheel
pip install pyusb paho-mqtt
pip install evdev
if [[ "${WITH_AUDIO}" -eq 1 ]]; then
  pip install pygame pyttsx3
fi
if [[ "${WITH_TENSORFLOW}" -eq 1 ]]; then
  pip install tensorflow
fi
if [[ "${WITH_TFLITE}" -eq 1 ]]; then
  pip install tflite-runtime numpy
fi

echo "[6/6] Install complete."
echo ""
echo "Next steps:"
echo "1) Activate venv: source .venv/bin/activate"
echo "2) Start process services:"
echo "   python services/sbc_io_service.py"
echo "   python services/sbc_reader_service.py"
echo "   python services/sbc_writer_service.py"
echo "   python services/sbc_macro_service.py"
echo "   python services/sbc_model_service.py"
echo "   python services/sbc_ai_copilot_service.py"
echo "3) Import Node-RED flows from node_red/*.json"
echo ""
echo "Full guide: docs/SYSTEM_GUIDE.md"
