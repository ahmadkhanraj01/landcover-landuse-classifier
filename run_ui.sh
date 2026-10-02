#!/usr/bin/env bash
cd "$(dirname "$0")"
exec .venv/bin/python -m streamlit run app.py --server.port "${PORT:-8501}" "$@"
