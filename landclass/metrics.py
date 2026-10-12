"""Run report: time, cost, throughput, label coverage/confidence, and agreement between runs.

There is no ground truth in the records table, so "accuracy" here is *agreement* with a reference run
(e.g. a run with 1 record/call or a larger model), not correctness against human labels.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from . import runner
from .config import DEFAULT_THRESHOLDS
from .export import load_scores, select


def _wall_seconds(prog: dict) -> float | None:
    try:
        start = datetime.fromisoformat(prog["started_at"])
        end = datetime.fromisoformat(prog["updated_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return max((end - start).total_seconds(), 0.0)


def run_summary(run_dir: Path) -> dict:
    """Time, throughput and cost of one run."""
    prog = runner.read_progress(run_dir)
    done = prog.get("done", 0)
    wall = _wall_seconds(prog)
    cost = prog.get("cost_usd") or 0.0
    calls = prog.get("calls") or 0
    tokens_in, tokens_out = prog.get("input_tokens") or 0, prog.get("output_tokens") or 0
    return {
        "status": prog.get("status"),
        "records": done,
        "wall_seconds": wall,
        "records_per_second": done / wall if wall else None,
        "seconds_per_record": wall / done if wall and done else None,
        "calls": calls,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "tokens_per_record": (tokens_in + tokens_out) / done if done else None,
        "cost_usd": cost,
        "cost_per_record": cost / done if done else None,
        "cost_per_1000": cost / done * 1000 if done else None,
        "engine": prog.get("engine", ""),
    }


def label_quality(run_dir: Path, tax_key: str, thresholds: dict[int, float] | None = None) -> dict:
    """Coverage and confidence of the selected labels (no ground truth needed)."""
    th = thresholds or DEFAULT_THRESHOLDS
    scores = load_scores(run_dir, tax_key)
    if scores.empty:
        return {}
    sel = select(scores, th)
    chosen = sel[sel["selected"]]
    n_records = scores["id"].nunique()
    l1 = chosen[chosen["level"] == 1]
    has_child = set(zip(chosen["id"], chosen["parent"]))
    deepest = chosen[[(i, c) not in has_child for i, c in zip(chosen["id"], chosen["code"])]]
    return {
        "records": n_records,
        "with_label": chosen["id"].nunique(),
        "coverage": chosen["id"].nunique() / n_records,
        "labels_per_record": len(deepest) / n_records,
        "mean_l1_confidence": float(l1["prob"].mean()) if len(l1) else None,
        "high_confidence_share": float((l1["prob"] >= 0.8).mean()) if len(l1) else None,
        "reach_level": {int(lv): chosen.loc[chosen["level"] == lv, "id"].nunique() / n_records
                        for lv in (1, 2, 3)},
        "class_counts": l1.groupby("code").size().sort_values(ascending=False),
    }


def agreement(run_a: Path, run_b: Path, tax_key: str, level: int = 1,
              thresholds: dict[int, float] | None = None) -> dict | None:
    """How often two runs give the same label set on the records they share (per-record exact match
    and label-level precision/recall/F1 treating `run_b` as the reference)."""
    th = thresholds or DEFAULT_THRESHOLDS
    sets = []
    for d in (run_a, run_b):
        s = select(load_scores(d, tax_key), th)
        s = s[s["selected"] & (s["level"] == level)]
        sets.append(s.groupby("id")["code"].agg(frozenset))
    a, b = sets
    shared = sorted(set(load_scores(run_a, tax_key)["id"]) & set(load_scores(run_b, tax_key)["id"]))
    if not shared:
        return None
    empty = frozenset()
    tp = fp = fn = exact = 0
    for rid in shared:
        sa, sb = a.get(rid, empty), b.get(rid, empty)
        tp += len(sa & sb)
        fp += len(sa - sb)
        fn += len(sb - sa)
        exact += sa == sb
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"shared": len(shared), "exact_match": exact / len(shared),
            "precision": precision, "recall": recall, "f1": f1}


def comparable_runs(run_dir: Path) -> list[Path]:
    """Other runs that share at least one taxonomy with this run."""
    taxes = set(runner.read_run(run_dir)["taxonomies"])
    return [r for r in runner.list_runs()
            if r != run_dir and taxes & set(runner.read_run(r)["taxonomies"])
            and runner.read_progress(r).get("done", 0) > 0]
