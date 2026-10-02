"""GLiNER2.5-Decide cascade classifier.

For each taxonomy and each record:
  Level 1: score all enabled top-level classes.
  Level 2: for every Level 1 class with probability >= explore threshold,
           score its sub-classes (a separate small label set).
  Level 3: same, below each Level 2 class above the explore threshold.

Each call sees at most a handful of labels, which keeps the input short and the
labels distinct. A class with a single sub-class passes its probability down.
All probabilities are returned; the decision thresholds are applied later
(see export.py, where a sub-class only counts if its parent is selected), so
they can be tuned without re-running the model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from .config import CHUNK_OVERLAP, CHUNK_WORDS, DEFAULT_BATCH_SIZE, MODEL_ID
from .taxonomy import Node, Taxonomy


@dataclass
class Score:
    record_id: str
    level: int
    code: str
    parent: str
    prob: float


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def chunk_text(title: str, abstract: str, words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Title + abstract; long abstracts become overlapping chunks, each prefixed by the title."""
    title = (title or "").strip()
    toks = (abstract or "").split()
    if not toks:
        return [title]
    if len(toks) <= words:
        return [f"{title}. {' '.join(toks)}" if title else " ".join(toks)]
    step = words - overlap
    return [f"{title}. {' '.join(toks[i:i + words])}" for i in range(0, max(len(toks) - overlap, 1), step)]


class Engine:
    def __init__(self, model_id: str = MODEL_ID, device: str | None = None,
                 batch_size: int | None = DEFAULT_BATCH_SIZE, dtype: str | None = None):
        from gliner2.classification import Classifier

        from .hardware import detect, torch_dtype

        hw = detect()
        if device is not None and device != hw.device:
            hw.device, hw.dtype, hw.name = device, dtype or "fp32", device
        if dtype:
            hw.dtype = dtype
        if batch_size:
            hw.batch_size = batch_size
        self.hardware = hw
        self.clf = Classifier.from_pretrained(model_id).to(
            device=hw.device, dtype=torch_dtype(hw.dtype)).eval()
        self.device = hw.device
        self.batch_size = hw.batch_size
        self._schemas: dict[tuple, tuple] = {}

    # -- schemas ---------------------------------------------------------

    def _schema(self, tax: Taxonomy, parent: str | None, nodes: list[Node]):
        """Compiled schema + label->code map for one sibling group (cached)."""
        key = (tax.key, parent, tuple((n.code, n.name, n.hint) for n in nodes))
        if key not in self._schemas:
            from gliner2.classification import ClassificationSchema

            label_map = tax.label_map(nodes)
            labels = {label: tax.description(tax.nodes[code]) for label, code in label_map.items()}
            schema = ClassificationSchema().multi("classes", labels, instruction=tax.instruction)
            self._schemas[key] = (self.clf.compile_schema(schema), label_map)
        return self._schemas[key]

    # -- scoring ---------------------------------------------------------

    def _score(self, texts: list[str], compiled: list) -> list[dict[str, float]]:
        """Logits per text, batched by length; halves the batch on GPU out-of-memory."""
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out: list = [None] * len(texts)
        i = 0
        while i < len(order):
            idx = order[i:i + self.batch_size]
            try:
                res = self.clf.scorer.batch_score(
                    [texts[j] for j in idx], [compiled[j] for j in idx], batch_size=len(idx))
            except torch.OutOfMemoryError:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                if self.batch_size == 1:
                    raise
                self.batch_size = max(1, self.batch_size // 2)
                continue
            for j, r in zip(idx, res):
                out[j] = dict(r.tasks["classes"])
            i += len(idx)
        return out

    def _score_groups(self, tax: Taxonomy, jobs: list[tuple[str, str | None, list[Node]]],
                      chunks: dict[str, list[str]]) -> dict[tuple[str, str], float]:
        """jobs: (record_id, parent_code, sibling nodes). Returns {(record_id, code): prob}."""
        texts, compiled, owners = [], [], []
        for rid, parent, nodes in jobs:
            comp, label_map = self._schema(tax, parent, nodes)
            for t in chunks[rid]:
                texts.append(t)
                compiled.append(comp)
                owners.append((rid, label_map))
        best: dict[tuple[str, str], float] = {}
        for (rid, label_map), logits in zip(owners, self._score(texts, compiled)):
            for label, logit in logits.items():
                key = (rid, label_map[label])
                best[key] = max(best.get(key, -1e9), logit)   # max over chunks
        return {k: _sigmoid(v) for k, v in best.items()}

    def classify(self, tax: Taxonomy, records: list[dict], explore: float, max_level: int = 3) -> list[Score]:
        """records: dicts with id, title, abstract. Returns every computed probability
        down to `max_level`."""
        chunks = {r["id"]: chunk_text(r["title"], r["abstract"]) for r in records}
        scores: list[Score] = []
        roots = tax.roots()
        # frontier: (record_id, node) pairs whose children still need scoring
        frontier: list[tuple[str, Node]] = []

        probs = self._score_groups(tax, [(rid, None, roots) for rid in chunks], chunks)
        for (rid, code), p in probs.items():
            scores.append(Score(rid, 1, code, "", p))
            if p >= explore and max_level > 1:
                frontier.append((rid, tax.nodes[code]))

        while frontier:
            jobs, passed = [], []
            for rid, node in frontier:
                kids = [k for k in tax.children(node.code) if k.level <= max_level]
                if len(kids) > 1:
                    jobs.append((rid, node.code, kids))
                elif len(kids) == 1:
                    passed.append((rid, node, kids[0]))
            next_frontier: list[tuple[str, Node]] = []
            parent_prob = {(s.record_id, s.code): s.prob for s in scores}
            for rid, node, kid in passed:
                p = parent_prob[(rid, node.code)]
                scores.append(Score(rid, kid.level, kid.code, node.code, p))
                if kid.level < max_level:
                    next_frontier.append((rid, kid))
            if jobs:
                probs = self._score_groups(tax, jobs, chunks)
                for (rid, code), p in probs.items():
                    node = tax.nodes[code]
                    scores.append(Score(rid, node.level, code, node.parent, p))
                    if p >= explore and node.level < max_level:
                        next_frontier.append((rid, node))
            frontier = next_frontier
        return scores
