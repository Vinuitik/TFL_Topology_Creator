from __future__ import annotations

import json
import logging
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from typing import Dict, Iterable, List, Set, Tuple

import redis
import requests

from schemas import PipelineState
from service.llm import call_llm
from utils import is_literal as _is_literal_util

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

def _describe_batch(names: List[str]) -> Dict[str, str]:
    """Get descriptions for a batch of names in a single LLM call."""
    lines = "\n".join(f'{i + 1}. "{n}"' for i, n in enumerate(names))
    try:
        result = call_llm("entity_describe_batch", f"\n{lines}\n", model=_ENTITY_MODEL)
        descs = result.get("descriptions", [])
        return {name: (descs[i] if i < len(descs) and descs[i] else name)
                for i, name in enumerate(names)}
    except Exception as exc:
        log.warning("Batch describe failed: %s — using names as fallback", exc)
        return {name: name for name in names}


_EMBED_TIMEOUT = float(__import__("os").getenv("OLLAMA_TIMEOUT_SEC", "3600"))


def _embed(text: str) -> List[float]:
    try:
        r = requests.post(_EMBED_URL, json={"model": _EMBED_MODEL, "prompt": text}, timeout=_EMBED_TIMEOUT)
        r.raise_for_status()
        return r.json().get("embedding", [])
    except Exception as exc:  # pragma: no cover - network/model runtime dependent
        log.warning("Embedding request failed: %s", exc)
        return []


_SAME_THRESHOLD = float(os.getenv("ENTITY_SAME_THRESHOLD", "0.88"))


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
    base = "entities" if category.startswith("entities") else "relations"
    for name in names:
        if name not in descs:
            cached = r.get(f"{category}:desc:{name}") or r.get(f"{base}:desc:{name}")
            if cached:
                descs[name] = cached
        if name not in embeds:
            cached = r.get(f"{category}:emb:{name}") or r.get(f"{base}:emb:{name}")
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

    # Derive the base namespace ("entities" or "relations") for cross-stage cache lookup.
    # entity_classification stores under "entities:desc:*" / "relations:desc:*" regardless
    # of sub-category, so we check that key first before regenerating.
    _base = "entities" if category.startswith("entities") else "relations"

    log.info("[%s] %d truly new, %d prior canonicals", category, len(truly_new), len(known_canonicals))

    # Step 1 — descriptions for truly new items (batched LLM calls)
    descs: Dict[str, str] = {}
    needs_desc: List[str] = []
    for name in truly_new:
        cached = _get_redis().get(f"{category}:desc:{name}") or _get_redis().get(f"{_base}:desc:{name}")
        if cached is not None:
            descs[name] = cached
            _get_redis().set(f"{category}:desc:{name}", cached)
        else:
            needs_desc.append(name)

    for i in range(0, len(needs_desc), 15):
        batch = needs_desc[i: i + 15]
        for name, desc in _describe_batch(batch).items():
            descs[name] = desc
            _get_redis().set(f"{category}:desc:{name}", desc)
            _get_redis().set(f"{_base}:desc:{name}", desc)

    # Load descs for known canonicals (no regeneration)
    _load_desc_emb(category, sorted(known_canonicals), descs, {})
    log.info("[%s] step 1 done — %d descriptions (%d newly generated)", category, len(descs), len(needs_desc))

    # Step 2 — embeddings (parallel HTTP requests)
    embeds: Dict[str, List[float]] = {}
    needs_emb: List[str] = []
    for name in truly_new:
        raw = _get_redis().get(f"{category}:emb:{name}") or _get_redis().get(f"{_base}:emb:{name}")
        if raw:
            try:
                embeds[name] = json.loads(raw)
                _get_redis().set(f"{category}:emb:{name}", raw)
                continue
            except json.JSONDecodeError:
                pass
        needs_emb.append(name)

    if needs_emb:
        def _do_embed(name: str) -> tuple[str, List[float]]:
            return name, _embed(descs.get(name, name))

        with ThreadPoolExecutor(max_workers=4) as pool:
            for name, emb in pool.map(_do_embed, needs_emb):
                if emb:
                    embeds[name] = emb
                    _get_redis().set(f"{category}:emb:{name}", json.dumps(emb))

    # Load embeddings for known canonicals
    for name in sorted(known_canonicals):
        cached = _get_redis().get(f"{category}:emb:{name}")
        if cached:
            try:
                embeds[name] = json.loads(cached)
            except json.JSONDecodeError:
                pass
    log.info("[%s] step 2 done — %d embeddings (%d newly embedded)", category, len(embeds), len(needs_emb))

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

    # Step 4b — LLM cluster judge: for each multi-member cluster, ask LLM to confirm
    # all members are the same real-world entity. If not, disband the cluster.
    raw_clusters = list(dsu.clusters().values())
    disbands = 0
    for members in raw_clusters:
        if len(members) < 2:
            continue
        type_label = {
            "entities_class": "class",
            "entities_individual": "individual",
            "relations_object": "object_property",
            "relations_data": "datatype_property",
        }.get(category, "individual")
        try:
            result = call_llm(
                "entity_linking",
                f"\nInput type: {type_label}\nNames: {json.dumps(members)}\n",
                model=_ENTITY_MODEL,
            )
            if not result.get("same", True):
                log.info("[%s] LLM DISBANDED cluster (size=%d): %s", category, len(members), members)
                for m in members:
                    dsu.p[m] = m  # reset each member to its own root
                    dsu.rank[m] = 0
                disbands += 1
            else:
                log.info("[%s] LLM CONFIRMED cluster (size=%d): %s", category, len(members), members)
        except Exception as exc:
            log.warning("[%s] LLM cluster judge failed for %s: %s — keeping cluster", category, members, exc)

    if disbands:
        log.info("[%s] LLM disbanded %d cluster(s)", category, disbands)

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


# --- helpers ---

_is_literal = _is_literal_util


# --- state ---

def run_entity_linking(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return state

    try:
        return _run_entity_linking_impl(state, triplets)
    except Exception:
        log.error("entity_linking CRASHED — full traceback:", exc_info=True)
        raise


def _run_entity_linking_impl(state: PipelineState, triplets) -> PipelineState:
    entity_catalog = state.get("entity_catalog", {})

    # Exclude literal objects from entity linking
    raw_entities = list(
        {t.subject for t in triplets}
        | {t.object for t in triplets if not _is_literal(t.object)}
    )
    raw_relations = list({t.predicate for t in triplets})

    log.info("entity_linking: %d raw entities, %d raw relations", len(raw_entities), len(raw_relations))

    # Split entities by kind from catalog (default: individual)
    classes = [e for e in raw_entities if entity_catalog.get(e, {}).get("kind") == "class"]
    individuals = [e for e in raw_entities if entity_catalog.get(e, {}).get("kind") != "class"]

    # Split relations by kind from catalog (default: object_property)
    obj_props = [r for r in raw_relations if entity_catalog.get(r, {}).get("kind") != "datatype_property"]
    data_props = [r for r in raw_relations if entity_catalog.get(r, {}).get("kind") == "datatype_property"]

    log.info("entity_linking: classes=%d individuals=%d obj_props=%d data_props=%d",
             len(classes), len(individuals), len(obj_props), len(data_props))

    # Surface normalisation per group
    cls_norm_map, cls_reps = _group_by_surface(classes)
    ind_norm_map, ind_reps = _group_by_surface(individuals)
    obj_norm_map, obj_reps = _group_by_surface(obj_props)
    dat_norm_map, dat_reps = _group_by_surface(data_props)

    # Process each group independently — no cross-type merging
    log.info("entity_linking: processing entities_class (%d reps)...", len(cls_reps))
    cc_repr, cls_stats = _process("entities_class", cls_reps)
    log.info("entity_linking: processing entities_individual (%d reps)...", len(ind_reps))
    ci_repr, ind_stats = _process("entities_individual", ind_reps)
    log.info("entity_linking: processing relations_object (%d reps)...", len(obj_reps))
    co_repr, obj_stats = _process("relations_object", obj_reps)
    log.info("entity_linking: processing relations_data (%d reps)...", len(dat_reps))
    cd_repr, dat_stats = _process("relations_data", dat_reps)
    log.info("entity_linking: all groups processed")

    def _resolve_entity(name: str) -> str:
        if entity_catalog.get(name, {}).get("kind") == "class":
            rep = cls_norm_map.get(name, name)
            return cc_repr.get(rep, rep)
        rep = ind_norm_map.get(name, name)
        return ci_repr.get(rep, rep)

    def _resolve_relation(name: str) -> str:
        if entity_catalog.get(name, {}).get("kind") == "datatype_property":
            rep = dat_norm_map.get(name, name)
            return cd_repr.get(rep, rep)
        rep = obj_norm_map.get(name, name)
        return co_repr.get(rep, rep)

    all_conflicts = (
        cls_stats["consistency_conflicts"]
        + ind_stats["consistency_conflicts"]
        + obj_stats["consistency_conflicts"]
        + dat_stats["consistency_conflicts"]
    )

    return {
        **state,
        "triplets": [
            t.model_copy(update={
                "subject": _resolve_entity(t.subject),
                "predicate": _resolve_relation(t.predicate),
                "object": _resolve_entity(t.object) if not _is_literal(t.object) else t.object,
            })
            for t in triplets
        ],
        "entity_linking_stats": {
            "entities_class": cls_stats,
            "entities_individual": ind_stats,
            "relations_object": obj_stats,
            "relations_data": dat_stats,
            "threshold": _EXACT_THRESHOLD,
        },
        "linking_conflicts": all_conflicts,
    }
