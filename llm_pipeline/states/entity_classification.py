from __future__ import annotations

"""Classify entities as class/individual and relations as object/datatype property (+OWL characteristics),
then generate rdfs:label and rdfs:comment for each via the lightweight entity model.
Runs after extraction, before entity_linking.
"""

import json
import logging
import os
from typing import Any, Dict, List, Set

import redis
import requests

from schemas import PipelineState, Triplet
from service.llm import call_llm
from utils import cosine, find_knn_by_embedding, is_literal

log = logging.getLogger(__name__)

_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL")
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
_EMBED_URL = os.getenv("OLLAMA_EMBED_URL")
_EMBED_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SEC", "3600"))
_BATCH = 15
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
_MAX_USAGE_EXAMPLES = 3
_KNN_K = 3

_R: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _R
    if _R is None:
        _R = redis.from_url(_REDIS_URL, decode_responses=True)
    return _R


def _load_annotation(category: str, name: str) -> Dict[str, str] | None:
    cached = _get_redis().get(f"{category}:annotation:{name}")
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass
    return None


def _persist_annotation(category: str, name: str, entry: Dict[str, Any]) -> None:
    _get_redis().set(
        f"{category}:annotation:{name}",
        json.dumps({k: entry[k] for k in ("kind", "label", "comment",
                                           "symmetric", "transitive", "functional")
                    if k in entry}),
    )


_VALID_ENTITY_KINDS = {"class", "individual"}
_VALID_RELATION_KINDS = {"object_property", "datatype_property"}


def _load_all_labeled(category: str) -> Dict[str, str]:
    """Scan Redis for all annotated entities/relations → {name: kind} for KNN."""
    r = _get_redis()
    prefix = f"{category}:annotation:"
    result: Dict[str, str] = {}
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"{prefix}*", count=500)
        for key in keys:
            name = key[len(prefix):]
            try:
                data = json.loads(r.get(key) or "{}")
                if "kind" in data:
                    result[name] = data["kind"]
            except (json.JSONDecodeError, TypeError):
                pass
        if cursor == 0:
            break
    return result


def _describe(name: str) -> str:
    try:
        return call_llm(
            "entity_linking_describe", f"\nName: {name}\n", model=_ENTITY_MODEL
        ).get("description", name)
    except Exception as exc:
        log.warning("Description fallback for '%s': %s", name, exc)
        return name


def _embed(text: str) -> List[float]:
    try:
        r = requests.post(
            _EMBED_URL,
            json={"model": _EMBED_MODEL, "prompt": text},
            timeout=_EMBED_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("embedding", [])
    except Exception as exc:
        log.warning("Embed failed for text %.40r: %s", text, exc)
        return []


def _ensure_embeddings(
    category: str, names: List[str]
) -> Dict[str, List[float]]:
    """Generate description + embedding for every name not already in Redis.
    Uses the same Redis keys as entity_linking so its work is reused there.
    Returns {name: vector} for all names that have a valid embedding.
    """
    r = _get_redis()
    embeddings: Dict[str, List[float]] = {}
    total = len(names)
    for idx, name in enumerate(names, 1):
        # Description
        desc_key = f"{category}:desc:{name}"
        desc = r.get(desc_key)
        if desc is None:
            desc = _describe(name)
            r.set(desc_key, desc)

        # Embedding
        emb_key = f"{category}:emb:{name}"
        cached_emb = r.get(emb_key)
        if cached_emb:
            try:
                embeddings[name] = json.loads(cached_emb)
                continue
            except json.JSONDecodeError:
                pass
        emb = _embed(desc)
        if emb:
            embeddings[name] = emb
            r.set(emb_key, json.dumps(emb))

        if idx % 20 == 0 or idx == total:
            log.info("entity_classification: embedded %d/%d %s", idx, total, category)

    return embeddings


def _triplet_str(t: Triplet) -> str:
    return f'"{t.subject}" → {t.predicate} → "{t.object}"'


def _build_entity_context(names: Set[str], triplets: List[Triplet]) -> Dict[str, List[str]]:
    ctx: Dict[str, List[str]] = {n: [] for n in names}
    for t in triplets:
        s = _triplet_str(t)
        if t.subject in ctx and len(ctx[t.subject]) < _MAX_USAGE_EXAMPLES:
            ctx[t.subject].append(s)
        if t.object in ctx and len(ctx[t.object]) < _MAX_USAGE_EXAMPLES:
            ctx[t.object].append(s)
    return ctx


def _build_relation_context(
    names: Set[str], triplets: List[Triplet]
) -> tuple[Dict[str, List[str]], Dict[str, bool]]:
    ctx: Dict[str, List[str]] = {n: [] for n in names}
    has_literal: Dict[str, bool] = {n: False for n in names}
    for t in triplets:
        if t.predicate in ctx:
            s = _triplet_str(t)
            if len(ctx[t.predicate]) < _MAX_USAGE_EXAMPLES:
                ctx[t.predicate].append(s)
            if is_literal(t.object):
                has_literal[t.predicate] = True
    return ctx, has_literal


def _run_entity_batch(
    names: List[str],
    context: Dict[str, List[str]],
    labeled: Dict[str, str],
    embeddings: Dict[str, List[float]],
) -> List[Dict[str, str]]:
    lines = []
    for i, n in enumerate(names):
        usages = context.get(n, [])
        usage_str = ", ".join(f'"{u}"' for u in usages) if usages else "no usage available"
        knn = find_knn_by_embedding(n, embeddings.get(n, []), labeled, embeddings, k=_KNN_K)
        knn_str = ", ".join(knn) if knn else "none"
        lines.append(f'{i + 1}. name="{n}"  usage=[{usage_str}]  similar_known=[{knn_str}]')
    params = "\n" + "\n".join(lines) + "\n"
    try:
        result = call_llm("entity_classify", params, model=_ENTITY_MODEL)
        results = result.get("results", [])
        if len(results) < len(names):
            results.extend([{}] * (len(names) - len(results)))
        return results[: len(names)]
    except Exception as exc:
        log.warning("entity_classify batch failed: %s", exc)
        return [{}] * len(names)


def _run_relation_batch(
    names: List[str],
    context: Dict[str, List[str]],
    has_literal: Dict[str, bool],
    labeled: Dict[str, str],
    embeddings: Dict[str, List[float]],
) -> List[Dict[str, Any]]:
    lines = []
    for i, n in enumerate(names):
        usages = context.get(n, [])
        usage_str = ", ".join(f'"{u}"' for u in usages) if usages else "no usage available"
        lit = str(has_literal.get(n, False)).lower()
        knn = find_knn_by_embedding(n, embeddings.get(n, []), labeled, embeddings, k=_KNN_K)
        knn_str = ", ".join(knn) if knn else "none"
        lines.append(
            f'{i + 1}. name="{n}"  usage=[{usage_str}]'
            f'  has_literal_object={lit}  similar_known=[{knn_str}]'
        )
    params = "\n" + "\n".join(lines) + "\n"
    try:
        result = call_llm("relation_classify", params, model=_ENTITY_MODEL)
        results = result.get("results", [])
        if len(results) < len(names):
            results.extend([{}] * (len(names) - len(results)))
        return results[: len(names)]
    except Exception as exc:
        log.warning("relation_classify batch failed: %s", exc)
        return [{}] * len(names)


def _annotate_batch(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    params = "\n" + "\n".join(
        f'{i + 1}. name="{item["name"]}" type="{item["kind"]}"'
        for i, item in enumerate(items)
    ) + "\n"
    try:
        result = call_llm("entity_annotate", params, model=_ENTITY_MODEL)
        results = result.get("results", [])
        if len(results) < len(items):
            results.extend([{}] * (len(items) - len(results)))
        return results[: len(items)]
    except Exception as exc:
        log.warning("entity_annotate batch failed: %s", exc)
        return [{}] * len(items)


def run_entity_classification(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return {}

    entity_names: Set[str] = {
        name
        for t in triplets
        for name in (t.subject, t.object)
        if not is_literal(name)
    }
    relation_names: Set[str] = {t.predicate for t in triplets}

    entity_context = _build_entity_context(entity_names, triplets)
    relation_context, has_literal = _build_relation_context(relation_names, triplets)

    # Load already-labeled entities/relations from Redis for KNN context
    labeled_entities = _load_all_labeled("entities")
    labeled_relations = _load_all_labeled("relations")
    log.info(
        "entity_classification: KNN pool — %d labeled entities, %d labeled relations from Redis",
        len(labeled_entities), len(labeled_relations),
    )

    # Embed everything upfront — new names get desc+embedding generated and cached to Redis.
    # entity_linking reuses these same Redis keys, so no duplicate work.
    log.info("entity_classification: embedding all entities and relations for KNN...")
    entity_embeddings = _ensure_embeddings("entities", sorted(entity_names))
    relation_embeddings = _ensure_embeddings("relations", sorted(relation_names))

    # Seed the KNN pool with embeddings for already-labeled entities from Redis
    for name in list(labeled_entities):
        if name not in entity_embeddings:
            cached = _get_redis().get(f"entities:emb:{name}")
            if cached:
                try:
                    entity_embeddings[name] = json.loads(cached)
                except json.JSONDecodeError:
                    pass
    for name in list(labeled_relations):
        if name not in relation_embeddings:
            cached = _get_redis().get(f"relations:emb:{name}")
            if cached:
                try:
                    relation_embeddings[name] = json.loads(cached)
                except json.JSONDecodeError:
                    pass

    catalog: Dict[str, Dict[str, Any]] = {}

    entities_to_classify: List[str] = []
    for name in sorted(entity_names):
        hit = _load_annotation("entities", name)
        if hit:
            catalog[name] = hit
        else:
            entities_to_classify.append(name)

    relations_to_classify: List[str] = []
    for name in sorted(relation_names):
        hit = _load_annotation("relations", name)
        if hit:
            if has_literal.get(name, False) and hit.get("kind") != "datatype_property":
                hit = {**hit, "kind": "datatype_property"}
            catalog[name] = hit
        else:
            relations_to_classify.append(name)

    log.info(
        "entity_classification: cache hits — entities=%d/%d relations=%d/%d",
        len(entity_names) - len(entities_to_classify), len(entity_names),
        len(relation_names) - len(relations_to_classify), len(relation_names),
    )

    # Step 1: classify new entities (context + embedding KNN)
    for i in range(0, len(entities_to_classify), _BATCH):
        batch = entities_to_classify[i : i + _BATCH]
        results = _run_entity_batch(batch, entity_context, labeled_entities, entity_embeddings)
        for name, r in zip(batch, results):
            kind = r.get("type", "individual")
            if kind not in _VALID_ENTITY_KINDS:
                kind = "individual"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}
            labeled_entities[name] = kind  # grow KNN pool within this run

    # Step 2: classify new relations (context + embedding KNN + deterministic literal override)
    for i in range(0, len(relations_to_classify), _BATCH):
        batch = relations_to_classify[i : i + _BATCH]
        results = _run_relation_batch(batch, relation_context, has_literal, labeled_relations, relation_embeddings)
        for name, r in zip(batch, results):
            if has_literal.get(name, False):
                kind = "datatype_property"
                symmetric = transitive = functional = False
            else:
                kind = r.get("type", "object_property")
                if kind not in _VALID_RELATION_KINDS:
                    kind = "object_property"
                symmetric = bool(r.get("symmetric", False))
                transitive = bool(r.get("transitive", False))
                functional = bool(r.get("functional", False))
            catalog[name] = {
                "kind": kind,
                "symmetric": symmetric,
                "transitive": transitive,
                "functional": functional,
                "label": name,
                "comment": "",
            }
            labeled_relations[name] = kind

    # Step 3: annotate only newly classified items
    new_names = set(entities_to_classify) | set(relations_to_classify)
    items_to_annotate = [{"name": n, "kind": catalog[n]["kind"]} for n in sorted(new_names) if n in catalog]
    for i in range(0, len(items_to_annotate), _BATCH):
        batch = items_to_annotate[i : i + _BATCH]
        results = _annotate_batch(batch)
        for item, r in zip(batch, results):
            name = item["name"]
            catalog[name]["label"] = r.get("label", name) or name
            catalog[name]["comment"] = r.get("comment", "") or ""
            cat = "entities" if name in set(entities_to_classify) else "relations"
            _persist_annotation(cat, name, catalog[name])

    log.info(
        "entity_classification: %d entities (%d class, %d individual), "
        "%d relations (%d obj [%d sym, %d trans, %d func], %d data)",
        len(entity_names),
        sum(1 for n in entity_names if catalog.get(n, {}).get("kind") == "class"),
        sum(1 for n in entity_names if catalog.get(n, {}).get("kind") == "individual"),
        len(relation_names),
        sum(1 for n in relation_names if catalog.get(n, {}).get("kind") == "object_property"),
        sum(1 for n in relation_names if catalog.get(n, {}).get("kind") == "object_property" and catalog.get(n, {}).get("symmetric")),
        sum(1 for n in relation_names if catalog.get(n, {}).get("kind") == "object_property" and catalog.get(n, {}).get("transitive")),
        sum(1 for n in relation_names if catalog.get(n, {}).get("functional")),
        sum(1 for n in relation_names if catalog.get(n, {}).get("kind") == "datatype_property"),
    )

    return {"entity_catalog": catalog}
