"""Persistent score store: a record is classified (and paid for) once per setup.

Scores live in data/cache/<taxonomy>_<fingerprint>.csv (same columns as a run's scores file). The
fingerprint covers what changes the answer: model, explore threshold, max depth and the label
names/hints/enabled flags of that taxonomy. Change any of them and records are classified again;
change nothing and a new run reuses the stored scores without calling the API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
SCORE_COLUMNS = ["id", "level", "code", "parent", "prob"]


def fingerprint(tax_key: str, hints: pd.DataFrame, model: str, explore: float, max_level: int) -> str:
    h = hints[hints["taxonomy"] == tax_key].sort_values(["level", "code"])
    payload = json.dumps({"model": model, "explore": round(float(explore), 4), "max_level": int(max_level),
                          "hints": h[["code", "name", "hint", "enabled"]].fillna("").astype(str).values.tolist()})
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def path_for(tax_key: str, fp: str) -> Path:
    return CACHE_DIR / f"{tax_key}_{fp}.csv"


def load(tax_key: str, fp: str) -> dict[str, list[tuple]]:
    """record id -> [(level, code, parent, prob), ...]"""
    path = path_for(tax_key, fp)
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"id": str, "code": str, "parent": str, "prob": str}).fillna("")
    out: dict[str, dict] = {}
    for rid, level, code, parent, prob in df[SCORE_COLUMNS].itertuples(index=False):
        out.setdefault(rid, {})[code] = (int(level), code, parent, prob)   # last score per code wins
    return {rid: list(rows.values()) for rid, rows in out.items()}


def append(tax_key: str, fp: str, rows: list[tuple]) -> None:
    """rows: (id, level, code, parent, prob_string). Written whole-record at a time."""
    if not rows:
        return
    path = path_for(tax_key, fp)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        if new:
            f.write(",".join(SCORE_COLUMNS) + "\n")
        for rid, level, code, parent, prob in rows:
            f.write(f"{rid},{level},{code},{parent},{prob}\n")


def import_run(run_dir: Path) -> dict[str, int]:
    """Seed the store from a finished or partial run. Records already stored are left alone."""
    from .runner import read_run   # local import: runner imports this module

    cfg = read_run(run_dir)
    from .taxonomy import load_hints

    hints = load_hints(run_dir / "label_hints.csv")
    done_file = run_dir / "done_ids.txt"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    added = {}
    for tax_key in cfg["taxonomies"]:
        scores_file = run_dir / f"scores_{tax_key}.csv"
        if not scores_file.exists():
            continue
        fp = fingerprint(tax_key, hints, cfg.get("model", ""), cfg["explore_threshold"], cfg.get("max_level", 3))
        have = set(load(tax_key, fp))
        df = pd.read_csv(scores_file, dtype=str, keep_default_na=False)
        df = df[df["id"].isin(done) & ~df["id"].isin(have)].drop_duplicates(["id", "code"], keep="last")
        append(tax_key, fp, list(df[SCORE_COLUMNS].itertuples(index=False, name=None)))
        added[tax_key] = df["id"].nunique()
    return added
