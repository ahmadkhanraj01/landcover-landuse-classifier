#!/usr/bin/env bash
# One-time setup on Linux/macOS: creates .venv and installs dependencies.
#   ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp example.env .env
echo "Done. Put your MISTRAL_API_KEY in .env, then start the UI with ./run_ui.sh"
