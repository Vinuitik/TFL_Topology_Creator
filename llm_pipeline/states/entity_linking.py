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

_R: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _R
    if _R is None:
        _R = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    return _R
_EMBED_URL = os.getenv("OLLAMA_EMBED_URL")
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL")
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
        return call_llm("entity_linking_describe", f"\nName: {name}\n", model=_ENTITY_MODEL).get("description", name)
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


import config
_SAME_THRESHOLD = config.ENTITY_SAME_THRESHOLD

def _compare_by_embedding(pairs: List[Tuple[str, str, str, str]], embeds: Dict[str, List[float]]) -> List[bool]:
    return [_cosine(embeds.get(na, []), embeds.get(nb, [])) >= _SAME_THRESHOLD for na, _, nb, _ in pairs]


def _canonical(names: List[str]) -> str:
    try:
        return call_llm("entity_linking_canonical", f"\nNames: {json.dumps(names)}\n", model=_ENTITY_MODEL).get("canonical", names[0])
    except Exception as exc:  # pragma: no cover - dependent on external runtime
        log.warning("Canonical fallback for %s: %s", names, exc)
        return sorted(names, key=len)[0]


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


# --- surface normalisation ---

_LEADING_ARTICLES = re.compile(r'^(the|a|an)\s+', re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r'\s+')


def _normalize_surface(name: str) -> str:
    """Canonical form used only for grouping before DSU — never stored or returned."""
    n = name.strip().lower()
    n = _LEADING_ARTICLES.sub('', n)
    n = _NON_ALNUM.sub(' ', n)
    n = _WHITESPACE.sub(' ', n).strip()
    # simple depluralization: strip trailing 's' (not 'ss') if result >= 3 chars
    if n.endswith('s') and not n.endswith('ss') and len(n) > 3:
        n = n[:-1]
    return n


def _group_by_surface(items: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """Group surface forms by normalised key; pick best representative per group.

    Returns:
        norm_map: original surface → representative
        representatives: deduplicated list of representative forms to pass to _process
    """
    groups: Dict[str, List[str]] = {}
    for item in items:
        key = _normalize_surface(item)
        groups.setdefault(key, []).append(item)

    norm_map: Dict[str, str] = {}
    representatives: List[str] = []
    for variants in groups.values():
        # prefer: starts uppercase > more uppercase chars > longer
        rep = max(variants, key=lambda x: (x[:1].isupper(), sum(c.isupper() for c in x), len(x)))
        for v in variants:
            norm_map[v] = rep
        representatives.append(rep)

    return norm_map, representatives


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

def _scan_known_canonicals(category: str) -> Dict[str, str]:
    """Return {surface_form: canonical} for all entries persisted in previous runs."""
    r = _get_redis()
    prefix = f"{category}:canonical:"
    result: Dict[str, str] = {}
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"{prefix}*", count=200)
        for key in keys:
            surface = key[len(prefix):]
            canon = r.get(key)
            if canon:
                result[surface] = canon
        if cursor == 0:
            break
    return result


def _load_desc_emb(category: str, names: List[str], descs: Dict[str, str], embeds: Dict[str, List[float]]) -> None:
    """Populate descs/embeds for names that already have Redis entries. No generation."""
    r = _get_redis()
    for name in names:
        if name not in descs:
            cached = r.get(f"{category}:desc:{name}")
            if cached:
                descs[name] = cached
        if name not in embeds:
            cached = r.get(f"{category}:emb:{name}")
            if cached:
                try:
                    embeds[name] = json.loads(cached)
                except json.JSONDecodeError:
                    pass


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

    new_items = sorted(set(items))

    # Load all canonicals seen in previous runs; derive the known-canonical universe.
    prior_canonicals = _scan_known_canonicals(category)  # surface → canonical
    known_canonicals: Set[str] = set(prior_canonicals.values())

    # Map: if a new item was already canonicalised in a prior run, honour that immediately.
    already_resolved: Dict[str, str] = {}
    truly_new: List[str] = []
    for name in new_items:
        if name in prior_canonicals:
            already_resolved[name] = prior_canonicals[name]
        else:
            truly_new.append(name)

    if not truly_new:
        # Everything in this file is already known — return prior mappings directly.
        return already_resolved, {
            "mode": "exact",
            "total_items": len(new_items),
            "compared_pairs": 0,
            "same_pairs": 0,
            "clusters": 0,
            "consistency_conflicts": 0,
        }

    # Step 1 — descriptions for truly new items only
    descs: Dict[str, str] = {}
    for name in truly_new:
        key = f"{category}:desc:{name}"
        cached = _get_redis().get(key)
        if cached is not None:
            descs[name] = cached
        else:
            generated = _describe(name)
            _get_redis().set(key, generated)
            descs[name] = generated

    # Load desc/emb for known canonicals from Redis (no regeneration)
    _load_desc_emb(category, sorted(known_canonicals), descs, {})
    known_descs: Dict[str, str] = {}
    _load_desc_emb(category, sorted(known_canonicals), known_descs, {})
    descs.update(known_descs)

    # Step 2 — embeddings for truly new items only
    embeds: Dict[str, List[float]] = {}
    for name in truly_new:
        key = f"{category}:emb:{name}"
        cached = _get_redis().get(key)
        if cached:
            try:
                embeds[name] = json.loads(cached)
                continue
            except json.JSONDecodeError:
                pass
        emb = _embed(descs[name])
        embeds[name] = emb
        _get_redis().set(key, json.dumps(emb))

    # Load embeddings for known canonicals (already in Redis)
    known_embeds: Dict[str, List[float]] = {}
    for name in sorted(known_canonicals):
        cached = _get_redis().get(f"{category}:emb:{name}")
        if cached:
            try:
                known_embeds[name] = json.loads(cached)
            except json.JSONDecodeError:
                pass
    embeds.update(known_embeds)

    # Step 3 — pairs: (new × new) + (new × known_canonical); skip known × known
    universe = sorted(set(truly_new) | known_canonicals)
    exact_mode = len(universe) <= _EXACT_THRESHOLD

    if exact_mode:
        new_set = set(truly_new)
        pairs = [
            (a, b)
            for a, b in combinations(universe, 2)
            if a in new_set or b in new_set  # at least one side is new
        ]
    else:
        pairs = _optimized_pairs(universe, descs, embeds)
        new_set = set(truly_new)
        pairs = [(a, b) for a, b in pairs if a in new_set or b in new_set]

    same: List[Tuple[str, str]] = []
    decisions: Dict[Tuple[str, str], bool] = {}
    flags = _compare_by_embedding([(a, descs.get(a, a), b, descs.get(b, b)) for a, b in pairs], embeds)
    for pair, flag in zip(pairs, flags):
        decisions[_pair_key(*pair)] = bool(flag)
        if flag:
            same.append(pair)

    mode = "exact" if exact_mode else "hybrid"
    log.info("[%s] mode=%s same=%d compared=%d new=%d known_canonicals=%d",
             category, mode, len(same), len(pairs), len(truly_new), len(known_canonicals))

    # Step 4 — DSU on universe (new + known canonicals)
    dsu = _DSU(universe)
    for a, b in same:
        dsu.union(a, b)

    clusters = list(dsu.clusters().values())
    conflicts = _conflicts_in_clusters(decisions, clusters)
    if conflicts:
        log.warning("[%s] consistency conflicts inside clusters: %d", category, len(conflicts))

    # Step 5+6 — canonical per cluster; prefer existing known canonical if present
    canon_map: Dict[str, str] = {}
    for members in clusters:
        known_in_cluster = [m for m in members if m in known_canonicals]
        if known_in_cluster:
            canon = known_in_cluster[0]
        else:
            new_members = [m for m in members if m in new_set]
            canon = _canonical(new_members) if new_members else members[0]
        for m in members:
            if m in new_set:  # only remap/persist new surface forms
                canon_map[m] = canon
                _get_redis().set(f"{category}:canonical:{m}", canon)

    # Merge in already-resolved items from prior runs
    canon_map.update(already_resolved)

    return canon_map, {
        "mode": mode,
        "total_items": len(new_items),
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

    # Surface normalisation: group plural/case variants before DSU
    raw_entities = list({t.subject for t in triplets} | {t.object for t in triplets})
    raw_relations = list({t.predicate for t in triplets})

    ent_norm_map, ent_representatives = _group_by_surface(raw_entities)
    rel_norm_map, rel_representatives = _group_by_surface(raw_relations)

    ce_repr, entities_stats = _process("entities", ent_representatives)
    cr_repr, relations_stats = _process("relations", rel_representatives)

    # Compose: original → representative → canonical
    def _resolve_entity(name: str) -> str:
        rep = ent_norm_map.get(name, name)
        return ce_repr.get(rep, rep)

    def _resolve_relation(name: str) -> str:
        rep = rel_norm_map.get(name, name)
        return cr_repr.get(rep, rep)

    return {
        **state,
        "triplets": [
            t.model_copy(update={
                "subject": _resolve_entity(t.subject),
                "predicate": _resolve_relation(t.predicate),
                "object": _resolve_entity(t.object),
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
