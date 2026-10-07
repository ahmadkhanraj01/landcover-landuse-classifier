"""Mistral cascade classifier.

For each taxonomy and each record:
  Level 1: score all enabled top-level classes.
  Level 2: for every Level 1 class with probability >= explore threshold,
           score its sub-classes (a separate small label set).
  Level 3: same, below each Level 2 class above the explore threshold.

Each API call sees at most a handful of labels, which keeps the prompt short and
the labels distinct. The model returns a 0-1 confidence per label as JSON. A class
with a single sub-class passes its probability down. All scores are returned; the
decision thresholds are applied later (see export.py, where a sub-class only counts
if its parent is selected), so they can be tuned without re-running the model.
"""
from __future__ import annotations

import json
import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

from .config import (MAX_ABSTRACT_CHARS, MISTRAL_API_KEY, MISTRAL_CONCURRENCY, MISTRAL_MODEL,
                     MISTRAL_PACK, MISTRAL_RPM, MISTRAL_TPM, MISTRAL_URL, PRICE_INPUT_PER_M,
                     PRICE_OUTPUT_PER_M)
from .taxonomy import Node, Taxonomy

MAX_RETRIES = 8

SYSTEM_PROMPT = """You classify scientific records (title and abstract) for a soil and land research database.

Task: {instruction}.

You receive {n_records}, each starting with "Record <k>:". Score every record on its own, independently of the others.

For each class below, give a confidence between 0 and 1 that the record studies or describes it.
- Score high (0.8-1) only when the text explicitly names the class or clearly implies it as a real subject of the study (study area, sampled land, analysed surface, managed land). A passing mention, a comparison, a citation or a general topic scores low.
- Be specific: when a record names one crop, tree type or land type, score only that class high and score its siblings 0.1 or lower. Do not score a class high just because it is similar to or often found with the named one.
- If the text only uses a general term that covers the whole group (e.g. "cereals", "crops", "forest", "built-up") and does not name a specific class below, score every class in this list 0.3 or lower: the broader parent class already records it.
- Score 0 when the text gives no evidence. Datasets, maps, models, methods or theory papers that do not say which land they concern score 0 for every class. Never infer a class from general soil topics alone.
- Several classes may score high only if the text really covers several; scores need not add up to 1.
- Judge only from the text; do not guess from the title alone when the abstract says otherwise.

Classes (code: name - description):
{classes}

Answer with a JSON object with the keys {keys}. Each value is an object that maps every class code to its confidence for that record."""


@dataclass
class Score:
    record_id: str
    level: int
    code: str
    parent: str
    prob: float


class MistralError(RuntimeError):
    pass


def record_text(title: str, abstract: str) -> str:
    title = (title or "").strip()
    abstract = (abstract or "").strip()[:MAX_ABSTRACT_CHARS]
    return f"Title: {title}\n\nAbstract: {abstract}" if abstract else f"Title: {title}"


class RateLimiter:
    """Sliding one-minute window over requests and tokens, shared by all threads.
    Waiting here is cheaper than being refused (HTTP 429) and backing off."""

    def __init__(self, rpm: int, tpm: int):
        self.rpm, self.tpm = rpm, tpm
        self._lock = threading.Lock()
        self._window: deque[list] = deque()   # [time, tokens]

    def set_limits(self, rpm: int | None, tpm: int | None) -> None:
        with self._lock:
            self.rpm = int(rpm * 0.9) if rpm else self.rpm
            self.tpm = int(tpm * 0.9) if tpm else self.tpm

    def acquire(self, tokens: int) -> list:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._window and now - self._window[0][0] >= 60:
                    self._window.popleft()
                used = sum(e[1] for e in self._window)
                if not self._window or (len(self._window) < self.rpm and used + tokens <= self.tpm):
                    entry = [now, tokens]
                    self._window.append(entry)
                    return entry
                wait = max(0.05, 60 - (now - self._window[0][0]))
            time.sleep(min(wait, 2.0))

    def settle(self, entry: list, tokens: int) -> None:
        with self._lock:
            entry[1] = tokens


class Engine:
    def __init__(self, model: str = MISTRAL_MODEL, api_key: str = MISTRAL_API_KEY,
                 concurrency: int = MISTRAL_CONCURRENCY, pack: int = MISTRAL_PACK):
        if not api_key:
            raise MistralError("MISTRAL_API_KEY is not set. Add it to .env (see example.env).")
        self.model = model
        self.concurrency = max(1, concurrency)
        self.pack = max(1, pack)
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._prompts: dict[tuple, tuple[str, dict]] = {}
        self._limiter = RateLimiter(MISTRAL_RPM, MISTRAL_TPM)
        self._limits_read = False
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens * PRICE_INPUT_PER_M + self.output_tokens * PRICE_OUTPUT_PER_M) / 1e6

    def describe(self) -> str:
        return f"Mistral API · {self.model} · {self.pack} records/call · {self.concurrency} parallel"

    # -- prompts ---------------------------------------------------------

    def _prompt(self, tax: Taxonomy, parent: str | None, nodes: list[Node], n: int) -> tuple[str, dict]:
        """System prompt + JSON schema for one sibling group and `n` records per call (cached)."""
        key = (tax.key, parent, n, tax.instruction, tuple((x.code, x.name, x.hint) for x in nodes))
        if key not in self._prompts:
            lines = []
            for x in nodes:
                desc = tax.description(x)
                lines.append(f"{x.code}: {x.label}" + (f" - {desc}" if desc else ""))
            names = [f"r{i + 1}" for i in range(n)]
            system = SYSTEM_PROMPT.format(
                instruction=tax.instruction, classes="\n".join(lines),
                n_records="1 record" if n == 1 else f"{n} records",
                keys=", ".join(f'"{k}"' for k in names))
            one = {
                "type": "object",
                "properties": {x.code: {"type": "number", "minimum": 0, "maximum": 1} for x in nodes},
                "required": [x.code for x in nodes],
                "additionalProperties": False,
            }
            schema = {"type": "object", "properties": {k: one for k in names},
                      "required": names, "additionalProperties": False}
            self._prompts[key] = (system, schema)
        return self._prompts[key]

    # -- API -------------------------------------------------------------

    def _call(self, system: str, schema: dict, user: str, codes: list[str], n: int) -> list[dict[str, float]]:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "scores", "schema": schema, "strict": True}},
        }
        estimate = int((len(system) + len(user)) / 3.5) + 8 * len(codes) * n
        last = ""
        for attempt in range(MAX_RETRIES):
            if attempt:
                time.sleep(min(60, 2 ** attempt) * (0.5 + random.random()))
            entry = self._limiter.acquire(estimate)
            try:
                resp = requests.post(MISTRAL_URL, headers=self._headers, json=body, timeout=120)
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if resp.status_code == 429:
                last = f"HTTP 429: {resp.text[:200]}"
                time.sleep(float(resp.headers.get("retry-after") or 0) or 0)
                continue
            if resp.status_code in (500, 502, 503, 504):
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
            if resp.status_code in (401, 403):
                raise MistralError(f"Mistral rejected the API key (HTTP {resp.status_code})")
            if not resp.ok:
                raise MistralError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            if not self._limits_read:
                self._limits_read = True
                h = resp.headers
                self._limiter.set_limits(int(h.get("x-ratelimit-limit-req-minute") or 0) or None,
                                         int(h.get("x-ratelimit-limit-tokens-minute") or 0) or None)
            data = resp.json()
            usage = data.get("usage") or {}
            self._limiter.settle(entry, usage.get("total_tokens") or estimate)
            with self._lock:
                self.calls += 1
                self.input_tokens += usage.get("prompt_tokens", 0)
                self.output_tokens += usage.get("completion_tokens", 0)
            try:
                raw = json.loads(data["choices"][0]["message"]["content"])
                return [{c: min(1.0, max(0.0, float(raw[f"r{i + 1}"].get(c, 0.0)))) for c in codes}
                        for i in range(n)]
            except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
                last = f"unparseable answer ({type(e).__name__})"
        raise MistralError(f"Mistral call failed after {MAX_RETRIES} attempts: {last}")

    def _score_pack(self, tax: Taxonomy, parent: str | None, nodes: list[Node], rids: list[str],
                    texts: dict[str, str]) -> dict[str, dict[str, float]]:
        codes = [x.code for x in nodes]
        system, schema = self._prompt(tax, parent, nodes, len(rids))
        user = "\n\n".join(f"Record {i + 1}:\n{texts[r]}" for i, r in enumerate(rids))
        return dict(zip(rids, self._call(system, schema, user, codes, len(rids))))

    def _score_groups(self, tax: Taxonomy, jobs: list[tuple[str, str | None, list[Node]]],
                      texts: dict[str, str]) -> dict[tuple[str, str], float]:
        """jobs: (record_id, parent_code, sibling nodes). Records that share the same sibling
        group are scored together, `pack` per call. Returns {(record_id, code): prob}."""
        groups: dict[str | None, tuple[list[Node], list[str]]] = {}
        for rid, parent, nodes in jobs:
            groups.setdefault(parent, (nodes, []))[1].append(rid)
        tasks = [(parent, nodes, rids[i:i + self.pack])
                 for parent, (nodes, rids) in groups.items() for i in range(0, len(rids), self.pack)]

        def one(task):
            parent, nodes, rids = task
            try:
                return self._score_pack(tax, parent, nodes, rids, texts)
            except MistralError as e:
                if len(rids) == 1 or "API key" in str(e):
                    raise
                out = {}   # a pack that keeps failing is retried one record at a time
                for r in rids:
                    out.update(self._score_pack(tax, parent, nodes, [r], texts))
                return out

        out: dict[tuple[str, str], float] = {}
        with ThreadPoolExecutor(self.concurrency) as pool:
            for res in pool.map(one, tasks):
                for rid, probs in res.items():
                    for code, p in probs.items():
                        out[(rid, code)] = p
        return out

    # -- cascade ---------------------------------------------------------

    def classify(self, tax: Taxonomy, records: list[dict], explore: float, max_level: int = 3) -> list[Score]:
        """records: dicts with id, title, abstract. Returns every computed probability
        down to `max_level`."""
        texts = {r["id"]: record_text(r["title"], r["abstract"]) for r in records}
        scores: list[Score] = []
        roots = tax.roots()
        # frontier: (record_id, node) pairs whose children still need scoring
        frontier: list[tuple[str, Node]] = []

        probs = self._score_groups(tax, [(rid, None, roots) for rid in texts], texts)
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
                probs = self._score_groups(tax, jobs, texts)
                for (rid, code), p in probs.items():
                    node = tax.nodes[code]
                    scores.append(Score(rid, node.level, code, node.parent, p))
                    if p >= explore and node.level < max_level:
                        next_frontier.append((rid, node))
            frontier = next_frontier
        return scores
