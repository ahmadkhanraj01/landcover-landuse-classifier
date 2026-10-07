"""Paths and constants shared by the UI and the background runner."""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
OUTPUT_DIR = ROOT / "output"

SNAPSHOT_FILE = DATA_DIR / "records_snapshot.parquet"
SNAPSHOT_META = DATA_DIR / "records_snapshot.json"
LABEL_HINTS_FILE = ROOT / "label_hints.csv"

# Mistral API. MISTRAL_API_KEY is read from the environment or .env.
_env = dotenv_values(ENV_FILE)


def _setting(key: str, default: str) -> str:
    return os.environ.get(key) or _env.get(key) or default


MISTRAL_API_KEY = _setting("MISTRAL_API_KEY", "")
MISTRAL_MODEL = _setting("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_CONCURRENCY = int(_setting("MISTRAL_CONCURRENCY", "8"))   # parallel requests
MISTRAL_PACK = int(_setting("MISTRAL_PACK", "5"))                 # records scored per API call
# Client-side limits (per minute), used until the API reports the real ones. Keep below the account limits.
MISTRAL_RPM = int(_setting("MISTRAL_RPM", "90"))
MISTRAL_TPM = int(_setting("MISTRAL_TPM", "90000"))
# USD per million tokens, used only for the cost estimate shown in the UI.
PRICE_INPUT_PER_M = float(_setting("MISTRAL_PRICE_INPUT", "0.15"))
PRICE_OUTPUT_PER_M = float(_setting("MISTRAL_PRICE_OUTPUT", "0.60"))

# One entry per taxonomy: source CSV, display name, and the task instruction
# that is given to the model together with the labels.
TAXONOMIES = {
    "landcover": {
        "name": "Land cover",
        "csv": ROOT / "LandCover_Types.csv",
        "instruction": "Land cover types studied or described in this research record",
    },
    "landuse": {
        "name": "Land use",
        "csv": ROOT / "LandUse_Types.csv",
        "instruction": "Land use types studied or described in this research record",
    },
}

# Defaults for the cascade and for turning probabilities into labels.
DEFAULT_EXPLORE_THRESHOLD = 0.50   # descend into a branch when its probability >= this
DEFAULT_MAX_LEVEL = 3
DEFAULT_THRESHOLDS = {1: 0.60, 2: 0.50, 3: 0.50}
MAX_ABSTRACT_CHARS = 20000         # longer abstracts are cut
RECORDS_PER_STEP = 120             # records processed (and checkpointed) together
