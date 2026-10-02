#!/usr/bin/env bash
# One-time setup on Linux/macOS: creates .venv, installs dependencies, downloads the model.
#   ./setup.sh            (NVIDIA GPU or CPU; PyPI torch includes CUDA on Linux)
#   TORCH_INDEX=https://download.pytorch.org/whl/cu126 ./setup.sh   (pick a CUDA build)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [ -n "${TORCH_INDEX:-}" ]; then
  .venv/bin/python -m pip install torch --index-url "$TORCH_INDEX"
fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m landclass.download_model
[ -f .env ] || cp example.env .env
.venv/bin/python -m landclass.hardware
echo "Done. Start the UI with ./run_ui.sh"
