from __future__ import annotations

import json
import logging
import math
import os
import re
from itertools import combinations
from typing import Dict, Iterable, List, Set, Tuple

import redis
import requests

from schemas import PipelineState
from service.llm import call_llm

log = logging.getLogger(__name__)

_R = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)
_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://ollama:11434/api/embeddings")
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "gemma4:e4b")
_BATCH = 20
_EXACT_THRESHOLD = 350
_MAX_CANDIDATES_PER_ITEM = 40
_SIMILARITY_MIN = 0.55
_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "on",
    "and",
    "or",
    "by",
    "with",
    "from",
    "at",
    "is",
    "are",
}


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
    try:
        return call_llm("entity_linking_describe", f"\nName: {name}\n").get("description", name)
    except Exception as exc:  # pragma: no cover - dependent on external runtime
        log.warning("Description fallback for '%s': %s", name, exc)
        return name


def _embed(text: str) -> List[float]:
    try:
        r = requests.post(_EMBED_URL, json={"model": _EMBED_MODEL, "prompt": text}, timeout=60)
        r.raise_for_status()
        return r.json().get("embedding", [])
    except Exception as exc:  # pragma: no cover - network/model runtime dependent
        log.warning("Embedding request failed: %s", exc)
        return []


def _compare_batch(pairs: List[Tuple[str, str, str, str]]) -> List[bool]:
    # each pair becomes a 2-item group in the entity_linking prompt
    groups = "".join(
        f'Group {i+1}: ["{na}: {da}", "{nb}: {db}"]\n'
        for i, (na, da, nb, db) in enumerate(pairs)
    )
    try:
        results = call_llm("entity_linking", groups).get("results", [])
        flags = [r.get("same", False) for r in results]
        if len(flags) < len(pairs):
            flags.extend([False] * (len(pairs) - len(flags)))
        return flags[: len(pairs)]
    except Exception as exc:  # pragma: no cover - dependent on external runtime
        log.warning("Batch compare fallback for %d pairs: %s", len(pairs), exc)

        # Heuristic fallback: strict normalized equality only.
        out: List[bool] = []
        for na, _, nb, _ in pairs:
            out.append(_normalize_for_equality(na) == _normalize_for_equality(nb))
        return out


def _canonical(names: List[str]) -> str:
    try:
        return call_llm("entity_linking_canonical", f"\nNames: {json.dumps(names)}\n").get("canonical", names[0])
    except Exception as exc:  # pragma: no cover - dependent on external runtime
        log.warning("Canonical fallback for %s: %s", names, exc)
        return sorted(names, key=lambda x: (len(x), x))[0]


def _normalize_for_equality(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _norm_tokens(name: str) -> Set[str]:
    parts = re.findall(r"[a-z0-9]+", name.lower())
    return {p for p in parts if len(p) > 2 and p not in _STOPWORDS}


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _optimized_pairs(items: List[str], descs: Dict[str, str], embeds: Dict[str, List[float]]) -> List[Tuple[str, str]]:
    tokens = {x: _norm_tokens(x) for x in items}

    inverted: Dict[str, Set[str]] = {}
    for item, toks in tokens.items():
        for token in toks:
            inverted.setdefault(token, set()).add(item)

    pairs: Set[Tuple[str, str]] = set()
    for item in items:
        related: Set[str] = set()
        for token in tokens[item]:
            related.update(inverted.get(token, set()))
        related.discard(item)

        scored: List[Tuple[float, str]] = []
        for cand in related:
            union = tokens[item] | tokens[cand]
            jac = (len(tokens[item] & tokens[cand]) / len(union)) if union else 0.0
            sim = _cosine(embeds.get(item, []), embeds.get(cand, []))
            score = jac + 0.35 * sim
            if score >= _SIMILARITY_MIN:
                scored.append((score, cand))

        scored.sort(reverse=True)
        for _, cand in scored[:_MAX_CANDIDATES_PER_ITEM]:
            pairs.add(_pair_key(item, cand))

    return sorted(pairs)


def _conflicts_in_clusters(decisions: Dict[Tuple[str, str], bool], clusters: Iterable[List[str]]) -> List[Tuple[str, str]]:
    conflicts: List[Tuple[str, str]] = []
    for members in clusters:
        for a, b in combinations(members, 2):
            key = _pair_key(a, b)
            if key in decisions and decisions[key] is False:
                conflicts.append(key)
    return conflicts


# --- per-category pipeline ---

def _process(category: str, items: List[str]) -> Tuple[Dict[str, str], Dict[str, int | str]]:
    if not items:
        return {}, {
            "mode": "exact",
            "total_items": 0,
            "compared_pairs": 0,
            "same_pairs": 0,
            "clusters": 0,
            "consistency_conflicts": 0,
        }

    items = sorted(set(items))

    # Step 1 — descriptions
    descs: Dict[str, str] = {}
    for name in items:
        key = f"{category}:desc:{name}"
        cached = _R.get(key)
        if cached is not None:
            descs[name] = cached
            continue

        generated = _describe(name)
        _R.set(key, generated)
        descs[name] = generated

    # Step 2 — embeddings (fire-and-forget into Redis, used for future ANN)
    embeds: Dict[str, List[float]] = {}
    for name in items:
        key = f"{category}:emb:{name}"
        cached = _R.get(key)
        if cached:
            try:
                embeds[name] = json.loads(cached)
                continue
            except json.JSONDecodeError:
                pass

        emb = _embed(descs[name])
        embeds[name] = emb
        _R.set(key, json.dumps(emb))

    # Step 3 — candidate pair generation and LLM comparison (batched)
    exact_mode = len(items) <= _EXACT_THRESHOLD
    pairs = list(combinations(items, 2)) if exact_mode else _optimized_pairs(items, descs, embeds)
    same: List[Tuple[str, str]] = []
    decisions: Dict[Tuple[str, str], bool] = {}
    for i in range(0, len(pairs), _BATCH):
        batch = pairs[i : i + _BATCH]
        flags = _compare_batch([(a, descs[a], b, descs[b]) for a, b in batch])
        for pair, flag in zip(batch, flags):
            decisions[_pair_key(*pair)] = bool(flag)
            if flag:
                same.append(pair)

    mode = "exact" if exact_mode else "hybrid"
    log.info("[%s] mode=%s same=%d compared=%d", category, mode, len(same), len(pairs))

    # Step 4 — DSU clustering
    dsu = _DSU(items)
    for a, b in same:
        dsu.union(a, b)

    clusters = list(dsu.clusters().values())
    conflicts = _conflicts_in_clusters(decisions, clusters)
    if conflicts:
        log.warning("[%s] consistency conflicts inside clusters: %d", category, len(conflicts))

    # Step 5+6 — canonical name per cluster, persist
    canon_map: Dict[str, str] = {}
    for members in clusters:
        canon = _canonical(members)
        for m in members:
            canon_map[m] = canon
            _R.set(f"{category}:canonical:{m}", canon)

    return canon_map, {
        "mode": mode,
        "total_items": len(items),
        "compared_pairs": len(pairs),
        "same_pairs": len(same),
        "clusters": len(clusters),
        "consistency_conflicts": len(conflicts),
    }


# --- state ---

def run_entity_linking(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return state

    ce, entities_stats = _process("entities", list({t.subject for t in triplets} | {t.object for t in triplets}))
    cr, relations_stats = _process("relations", list({t.predicate for t in triplets}))

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
        "entity_linking_stats": {
            "entities": entities_stats,
            "relations": relations_stats,
            "threshold": _EXACT_THRESHOLD,
        },
        "linking_conflicts": entities_stats["consistency_conflicts"] + relations_stats["consistency_conflicts"],
    }
