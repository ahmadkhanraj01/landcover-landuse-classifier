#!/usr/bin/env bash
# Whole pipeline, then the UI:  classify -> CSV files -> database -> Streamlit
#   ./run_all.sh --sample 20                  # random 20 records
#   ./run_all.sh                              # all records
#   ./run_all.sh --resume runs/<run_id>       # continue an interrupted run
#   ./run_all.sh --sample 20 --no-db          # skip the database step
# Other options: see `python pipeline.py --help`. PORT=8502 ./run_all.sh changes the UI port.
cd "$(dirname "$0")"

[ -x .venv/bin/python ] || ./setup.sh || exit 1
[ -f .env ] || { echo "No .env: copy example.env to .env and fill it in."; exit 1; }

if ! .venv/bin/python pipeline.py "$@"; then
    echo "Pipeline did not finish (see the message above). Opening the UI anyway."
fi

exec ./run_ui.sh
