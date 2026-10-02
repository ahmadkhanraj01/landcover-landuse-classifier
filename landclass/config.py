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

# A copy in models/ (made by `pack.sh --with-model`) is used when present, so a
# packed folder works offline. LANDCLASS_MODEL overrides both.
MODEL_HUB_ID = "fastino/GLiNER2.5-Decide"
LOCAL_MODEL_DIR = ROOT / "models" / "GLiNER2.5-Decide"
MODEL_ID = (os.environ.get("LANDCLASS_MODEL") or dotenv_values(ENV_FILE).get("LANDCLASS_MODEL") or (
    str(LOCAL_MODEL_DIR) if (LOCAL_MODEL_DIR / "config.json").exists() else MODEL_HUB_ID))

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
DEFAULT_BATCH_SIZE = None          # None = pick from GPU memory (see hardware.py)
CHUNK_WORDS = 300                  # long abstracts are split into chunks of this many words
CHUNK_OVERLAP = 50
RECORDS_PER_STEP = 128             # minimum records processed (and checkpointed) together
