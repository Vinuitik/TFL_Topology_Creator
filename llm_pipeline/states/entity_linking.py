from __future__ import annotations

"""Canonicalize entity spans appearing across triplets via description, embedding, pairwise LLM comparison, DSU clustering, and canonical naming."""

import json
import logging
from itertools import combinations
from typing import Dict, List, Tuple

import redis
import requests

from schemas import PipelineState
from service.llm import call_llm

log = logging.getLogger(__name__)

_REDIS_URL = "redis://redis:6379"
_OLLAMA_EMBED_URL = "http://ollama:11434/api/embeddings"
_EMBED_MODEL = "deepseek-r1:7b"
_PAIR_BATCH_SIZE = 20


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

def _redis() -> redis.Redis:
    return redis.from_url(_REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# Step 1 — Description generation
# ---------------------------------------------------------------------------

def _generate_description(name: str) -> str:
    result = call_llm("entity_linking_describe", f"\nName: {name}\n")
    return result.get("description", name)


# ---------------------------------------------------------------------------
# Step 2 — Embedding
# ---------------------------------------------------------------------------

def _embed(text: str) -> List[float]:
    resp = requests.post(
        _OLLAMA_EMBED_URL,
        json={"model": _EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ---------------------------------------------------------------------------
# Step 3 — Pairwise LLM comparison
# ---------------------------------------------------------------------------

def _pairwise_compare(pairs: List[Tuple[str, str, str, str]]) -> List[bool]:
    """
    pairs: list of (name_a, desc_a, name_b, desc_b)
    Batches them as groups into the entity_linking prompt.
    Returns a bool per pair.
    """
    groups_text = ""
    for i, (na, da, nb, db) in enumerate(pairs):
        groups_text += f'Group {i + 1}: ["{na}: {da}", "{nb}: {db}"]\n'
    result = call_llm("entity_linking", groups_text)
    results = result.get("results", [])
    return [r.get("same", False) for r in results]


# ---------------------------------------------------------------------------
# Step 4 — DSU
# ---------------------------------------------------------------------------

class _DSU:
    def __init__(self, items: List[str]) -> None:
        self.parent = {x: x for x in items}
        self.rank: Dict[str, int] = {x: 0 for x in items}

    def find(self, x: str) -> str:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def clusters(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for x in self.parent:
            root = self.find(x)
            result.setdefault(root, []).append(x)
        return result


# ---------------------------------------------------------------------------
# Step 5 — Canonical naming
# ---------------------------------------------------------------------------

def _canonical_name(names: List[str]) -> str:
    result = call_llm("entity_linking_canonical", f"\nNames: {json.dumps(names)}\n")
    return result.get("canonical", names[0])


# ---------------------------------------------------------------------------
# Per-category pipeline
# ---------------------------------------------------------------------------

def _process_category(r: redis.Redis, category: str, items: List[str]) -> Dict[str, str]:
    """Runs all 6 steps for one category. Returns original_name -> canonical_name."""
    if not items:
        return {}

    # Step 1 — descriptions (skip if cached)
    descriptions: Dict[str, str] = {}
    for name in items:
        key = f"{category}:desc:{name}"
        cached = r.get(key)
        if cached:
            descriptions[name] = cached
        else:
            desc = _generate_description(name)
            r.set(key, desc)
            descriptions[name] = desc
            log.debug("[%s] generated description for %r", category, name)

    # Step 2 — embeddings (skip if cached)
    for name in items:
        key = f"{category}:emb:{name}"
        if not r.exists(key):
            emb = _embed(descriptions[name])
            r.set(key, json.dumps(emb))
            log.debug("[%s] embedded %r", category, name)

    # Step 3 — pairwise LLM comparison (batched)
    pairs = list(combinations(items, 2))
    same_pairs: List[Tuple[str, str]] = []
    if pairs:
        all_results: List[bool] = []
        for i in range(0, len(pairs), _PAIR_BATCH_SIZE):
            batch = pairs[i : i + _PAIR_BATCH_SIZE]
            inputs = [(a, descriptions[a], b, descriptions[b]) for a, b in batch]
            all_results.extend(_pairwise_compare(inputs))
        same_pairs = [pairs[i] for i, is_same in enumerate(all_results) if is_same]
    log.info("[%s] %d/%d pairs judged same", category, len(same_pairs), len(pairs))

    # Step 4 — DSU clustering
    dsu = _DSU(items)
    for a, b in same_pairs:
        dsu.union(a, b)
    clusters = dsu.clusters()
    log.info("[%s] %d cluster(s) from %d item(s)", category, len(clusters), len(items))

    # Step 5 — canonical naming
    canonical_map: Dict[str, str] = {}
    for members in clusters.values():
        canon = _canonical_name(members)
        for m in members:
            canonical_map[m] = canon

    # Step 6 — persist
    for name, canon in canonical_map.items():
        r.set(f"{category}:canonical:{name}", canon)

    return canonical_map


# ---------------------------------------------------------------------------
# State entrypoint
# ---------------------------------------------------------------------------

def run_entity_linking(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return state

    r = _redis()

    entity_names = list({t.subject for t in triplets} | {t.object for t in triplets})
    relation_names = list({t.predicate for t in triplets})

    log.info("Entity linking: %d entities, %d relations", len(entity_names), len(relation_names))

    canonical_entities = _process_category(r, "entities", entity_names)
    canonical_relations = _process_category(r, "relations", relation_names)

    new_triplets = [
        t.model_copy(update={
            "subject": canonical_entities.get(t.subject, t.subject),
            "predicate": canonical_relations.get(t.predicate, t.predicate),
            "object": canonical_entities.get(t.object, t.object),
        })
        for t in triplets
    ]

    return {**state, "triplets": new_triplets}
