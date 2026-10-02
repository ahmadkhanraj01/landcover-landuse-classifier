"""Turn a run's probabilities into labels and CSV files.

A class is selected when its probability >= the threshold for its level AND
(for Level 2/3) its parent class is selected. The "deepest" labels are the
selected classes with no selected sub-class: the most specific answer.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import OUTPUT_DIR
from .data import load_snapshot
from .taxonomy import Taxonomy, build_taxonomy, load_hints

SEP = "; "


def load_scores(run_dir: Path, tax_key: str) -> pd.DataFrame:
    path = run_dir / f"scores_{tax_key}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["id", "level", "code", "parent", "prob"])
    df = pd.read_csv(path, dtype={"id": str, "code": str, "parent": str})
    df["parent"] = df["parent"].fillna("")
    # a resumed run can repeat a step; keep the last score per (id, code)
    return df.drop_duplicates(["id", "code"], keep="last")


def run_taxonomy(run_dir: Path, tax_key: str) -> Taxonomy:
    return build_taxonomy(tax_key, load_hints(run_dir / "label_hints.csv"))


def select(scores: pd.DataFrame, thresholds: dict[int, float]) -> pd.DataFrame:
    """Scores with a boolean `selected` column (threshold + parent selected)."""
    s = scores.copy()
    s["selected"] = False
    chosen: set[tuple[str, str]] = set()
    for level in sorted(s["level"].unique()):
        m = s["level"] == level
        ok = s.loc[m, "prob"] >= thresholds.get(int(level), 0.5)
        if level > 1:
            parent_ok = [(i, p) in chosen for i, p in zip(s.loc[m, "id"], s.loc[m, "parent"])]
            ok &= pd.Series(parent_ok, index=ok.index)
        s.loc[m, "selected"] = ok
        chosen |= set(zip(s.loc[m & s["selected"], "id"], s.loc[m & s["selected"], "code"]))
    return s


def wide_table(selected: pd.DataFrame, tax: Taxonomy, records: pd.DataFrame) -> pd.DataFrame:
    """One row per record: deepest labels, per-level labels, probabilities."""
    sel = selected[selected["selected"]].sort_values(["id", "level", "code"])
    has_child = set(zip(sel["id"], sel["parent"]))
    rows = {}
    for rid, g in sel.groupby("id"):
        row = {}
        deepest = g[[(rid, c) not in has_child for c in g["code"]]]
        row["codes"] = SEP.join(deepest["code"])
        row["labels"] = SEP.join(tax.nodes[c].name for c in deepest["code"])
        row["probabilities"] = SEP.join(f"{c}={p:.2f}" for c, p in zip(deepest["code"], deepest["prob"]))
        for level in (1, 2, 3):
            lv = g[g["level"] == level]
            row[f"L{level}_codes"] = SEP.join(lv["code"])
            row[f"L{level}_labels"] = SEP.join(tax.nodes[c].name for c in lv["code"])
        row["n_labels"] = len(deepest)
        rows[rid] = row
    cols = ["codes", "labels", "probabilities"] + [f"L{l}_{k}" for l in (1, 2, 3) for k in ("codes", "labels")] + ["n_labels"]
    out = pd.DataFrame.from_dict(rows, orient="index", columns=cols)
    out = records[["id", "identifier", "title"]].merge(out, left_on="id", right_index=True, how="left")
    out[cols[:-1]] = out[cols[:-1]].fillna("")
    out["n_labels"] = out["n_labels"].fillna(0).astype(int)
    return out


def long_table(selected: pd.DataFrame, tax: Taxonomy) -> pd.DataFrame:
    out = selected.copy()
    out["label"] = [tax.nodes[c].name for c in out["code"]]
    out["prob"] = out["prob"].round(4)
    return out[["id", "level", "code", "label", "parent", "prob", "selected"]].sort_values(["id", "level", "code"])


def run_records(run_dir: Path) -> pd.DataFrame:
    ids = [l for l in (run_dir / "ids.txt").read_text().split("\n") if l]
    done_file = run_dir / "done_ids.txt"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    snap = load_snapshot()
    return snap[snap["id"].isin(done & set(ids))]


def export(run_dir: Path, tax_key: str, thresholds: dict[int, float],
           include_abstract: bool = False) -> tuple[Path, Path]:
    tax = run_taxonomy(run_dir, tax_key)
    records = run_records(run_dir)
    selected = select(load_scores(run_dir, tax_key), thresholds)
    wide = wide_table(selected, tax, records)
    if include_abstract:
        wide = wide.merge(records[["id", "abstract"]], on="id", how="left")
    out_dir = OUTPUT_DIR / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    wide_path = out_dir / f"{tax_key}_results.csv"
    long_path = out_dir / f"{tax_key}_scores_long.csv"
    wide.to_csv(wide_path, index=False)
    long_table(selected, tax).to_csv(long_path, index=False)
    (out_dir / f"{tax_key}_thresholds.txt").write_text(
        "\n".join(f"{tax_key} L{l}: {t}" for l, t in sorted(thresholds.items())) + "\n")
    return wide_path, long_path
