from __future__ import annotations

import json
import logging
from itertools import combinations
from typing import Dict, List, Tuple

import redis
import requests

from schemas import PipelineState
from service.llm import call_llm

log = logging.getLogger(__name__)

_R = redis.from_url("redis://redis:6379", decode_responses=True)
_EMBED_URL = "http://ollama:11434/api/embeddings"
_EMBED_MODEL = "deepseek-r1:7b"
_BATCH = 20


# --- DSU ---

class _DSU:
    def __init__(self, items: List[str]) -> None:
        self.p = {x: x for x in items}
        self.rank: Dict[str, int] = {x: 0 for x in items}

    def find(self, x: str) -> str:
        if self.p[x] != x:
            self.p[x] = self.find(self.p[x])
        return self.p[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def clusters(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for x in self.p:
            out.setdefault(self.find(x), []).append(x)
        return out


# --- helpers ---

def _describe(name: str) -> str:
    return call_llm("entity_linking_describe", f"\nName: {name}\n").get("description", name)


def _embed(text: str) -> List[float]:
    r = requests.post(_EMBED_URL, json={"model": _EMBED_MODEL, "prompt": text}, timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]


def _compare_batch(pairs: List[Tuple[str, str, str, str]]) -> List[bool]:
    # each pair becomes a 2-item group in the entity_linking prompt
    groups = "".join(
        f'Group {i+1}: ["{na}: {da}", "{nb}: {db}"]\n'
        for i, (na, da, nb, db) in enumerate(pairs)
    )
    results = call_llm("entity_linking", groups).get("results", [])
    return [r.get("same", False) for r in results]


def _canonical(names: List[str]) -> str:
    return call_llm("entity_linking_canonical", f"\nNames: {json.dumps(names)}\n").get("canonical", names[0])


# --- per-category pipeline ---

def _process(category: str, items: List[str]) -> Dict[str, str]:
    if not items:
        return {}

    # Step 1 — descriptions
    descs: Dict[str, str] = {}
    for name in items:
        key = f"{category}:desc:{name}"
        descs[name] = _R.get(key) or _R.set(key, d := _describe(name)) or d

    # Step 2 — embeddings (fire-and-forget into Redis, used for future ANN)
    for name in items:
        key = f"{category}:emb:{name}"
        if not _R.exists(key):
            _R.set(key, json.dumps(_embed(descs[name])))

    # Step 3 — pairwise LLM comparison (batched)
    pairs = list(combinations(items, 2))
    same: List[Tuple[str, str]] = []
    for i in range(0, len(pairs), _BATCH):
        batch = pairs[i : i + _BATCH]
        flags = _compare_batch([(a, descs[a], b, descs[b]) for a, b in batch])
        same.extend(p for p, f in zip(batch, flags) if f)
    log.info("[%s] %d/%d pairs same", category, len(same), len(pairs))

    # Step 4 — DSU clustering
    dsu = _DSU(items)
    for a, b in same:
        dsu.union(a, b)

    # Step 5+6 — canonical name per cluster, persist
    canon_map: Dict[str, str] = {}
    for members in dsu.clusters().values():
        canon = _canonical(members)
        for m in members:
            canon_map[m] = canon
            _R.set(f"{category}:canonical:{m}", canon)

    return canon_map


# --- state ---

def run_entity_linking(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return state

    ce = _process("entities", list({t.subject for t in triplets} | {t.object for t in triplets}))
    cr = _process("relations", list({t.predicate for t in triplets}))

    return {
        **state,
        "triplets": [
            t.model_copy(update={
                "subject": ce.get(t.subject, t.subject),
                "predicate": cr.get(t.predicate, t.predicate),
                "object": ce.get(t.object, t.object),
            })
            for t in triplets
        ],
    }
