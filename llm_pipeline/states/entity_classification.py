from __future__ import annotations

"""Classify entities as class/individual and relations as object/datatype property (+OWL characteristics),
then generate rdfs:label and rdfs:comment for each via the lightweight entity model.
Runs after extraction, before entity_linking.
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
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
_BATCH = int(os.getenv("CLASSIFY_BATCH_SIZE", "15"))
_KNN_K = int(os.getenv("CLASSIFY_KNN_K", "3"))
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
_MAX_USAGE_EXAMPLES = 3

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


def _describe_batch(names: List[str]) -> Dict[str, str]:
    """Get descriptions for a batch of names in a single LLM call."""
    lines = "\n".join(f'{i + 1}. "{n}"' for i, n in enumerate(names))
    try:
        result = call_llm(
            "entity_describe_batch", f"\n{lines}\n", model=_ENTITY_MODEL,
            extra_options={"repeat_penalty": 1.4, "num_predict": 512},
            timeout=120.0,
        )
        descs = result.get("descriptions", [])
        if not isinstance(descs, list):
            raise ValueError(f"Expected list, got {type(descs)}")
        return {name: (str(descs[i]).strip() if i < len(descs) and descs[i] else name)
                for i, name in enumerate(names)}
    except Exception as exc:
        log.warning("Batch describe failed: %s — using names as fallback", exc)
        return {name: name for name in names}


def _embed(text: str) -> List[float]:
    import time as _time
    for attempt in range(3):
        try:
            r = requests.post(
                _EMBED_URL,
                json={"model": _EMBED_MODEL, "prompt": text},
                timeout=_EMBED_TIMEOUT,
            )
            r.raise_for_status()
            return r.json().get("embedding", [])
        except Exception as exc:
            if attempt < 2:
                _time.sleep(0.5 * (attempt + 1))
                continue
            log.warning("Embed failed for text %.40r: %s", text, exc)
            return []
    return []


_EMBED_WORKERS = int(os.getenv("EMBED_WORKERS", "4"))


def _ensure_embeddings(category: str, names: List[str]) -> Dict[str, List[float]]:
    """Batch-describe then parallel-embed all names not already cached in Redis."""
    r = _get_redis()
    descs: Dict[str, str] = {}
    embeddings: Dict[str, List[float]] = {}

    # Pass 1: load cached descriptions, collect what needs generating
    needs_desc: List[str] = []
    for name in names:
        cached = r.get(f"{category}:desc:{name}")
        if cached is not None:
            descs[name] = cached
        else:
            needs_desc.append(name)

    # Pass 2: batch LLM describe for uncached names
    total_batches = max(1, (len(needs_desc) + _BATCH - 1) // _BATCH)
    t_last = time.monotonic()
    for batch_idx, i in enumerate(range(0, len(needs_desc), _BATCH), 1):
        batch = needs_desc[i: i + _BATCH]
        batch_descs = _describe_batch(batch)
        for name, desc in batch_descs.items():
            descs[name] = desc
            r.set(f"{category}:desc:{name}", desc)
        pct = batch_idx / total_batches * 100
        if pct >= 100 or batch_idx % max(1, total_batches // 4) == 0:
            now = time.monotonic()
            log.info("[%s] describe %d/%d batches (%.0f%%) — %.1fs since last checkpoint",
                     category, batch_idx, total_batches, pct, now - t_last)
            t_last = now

    log.info("entity_classification: %d descriptions ready for %s (%d newly generated)",
             len(descs), category, len(needs_desc))

    # Pass 3: load cached embeddings, collect what needs embedding
    needs_emb: List[str] = []
    for name in names:
        cached = r.get(f"{category}:emb:{name}")
        if cached:
            try:
                embeddings[name] = json.loads(cached)
                continue
            except json.JSONDecodeError:
                pass
        needs_emb.append(name)

    # Pass 4: parallel embed
    if needs_emb:
        def _do_embed(name: str) -> tuple[str, List[float]]:
            return name, _embed(descs.get(name, name))

        t_emb = time.monotonic()
        log.info("[%s] embedding %d items (parallel workers=%d)...", category, len(needs_emb), _EMBED_WORKERS)
        with ThreadPoolExecutor(max_workers=_EMBED_WORKERS) as pool:
            for name, emb in pool.map(_do_embed, needs_emb):
                if emb:
                    embeddings[name] = emb
                    r.set(f"{category}:emb:{name}", json.dumps(emb))
        log.info("[%s] embed done — %d embedded in %.1fs", category, len(needs_emb), time.monotonic() - t_emb)

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

    def _progress(label: str, batch_idx: int, total_batches: int, t_last: float) -> float:
        now = time.monotonic()
        pct = batch_idx / total_batches * 100
        log.info("[classify] %s %d/%d batches (%.0f%%) — %.1fs since last checkpoint",
                 label, batch_idx, total_batches, pct, now - t_last)
        return now

    # Step 1: classify new entities (context + embedding KNN)
    total_e = max(1, (len(entities_to_classify) + _BATCH - 1) // _BATCH)
    t_last = time.monotonic()
    for batch_idx, i in enumerate(range(0, len(entities_to_classify), _BATCH), 1):
        batch = entities_to_classify[i : i + _BATCH]
        results = _run_entity_batch(batch, entity_context, labeled_entities, entity_embeddings)
        for name, r in zip(batch, results):
            kind = r.get("type", "individual")
            if kind not in _VALID_ENTITY_KINDS:
                kind = "individual"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}
            labeled_entities[name] = kind
        if batch_idx % max(1, total_e // 4) == 0 or batch_idx == total_e:
            t_last = _progress("entities", batch_idx, total_e, t_last)

    # Step 2: classify new relations (context + embedding KNN + deterministic literal override)
    total_r = max(1, (len(relations_to_classify) + _BATCH - 1) // _BATCH)
    t_last = time.monotonic()
    for batch_idx, i in enumerate(range(0, len(relations_to_classify), _BATCH), 1):
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
        if batch_idx % max(1, total_r // 4) == 0 or batch_idx == total_r:
            t_last = _progress("relations", batch_idx, total_r, t_last)

    # Step 3: annotate only newly classified items
    entities_to_classify_set = set(entities_to_classify)
    new_names = entities_to_classify_set | set(relations_to_classify)
    items_to_annotate = [{"name": n, "kind": catalog[n]["kind"]} for n in sorted(new_names) if n in catalog]
    total_a = max(1, (len(items_to_annotate) + _BATCH - 1) // _BATCH)
    t_last = time.monotonic()
    for batch_idx, i in enumerate(range(0, len(items_to_annotate), _BATCH), 1):
        batch = items_to_annotate[i : i + _BATCH]
        results = _annotate_batch(batch)
        for item, r in zip(batch, results):
            name = item["name"]
            catalog[name]["label"] = r.get("label", name) or name
            catalog[name]["comment"] = r.get("comment", "") or ""
            cat = "entities" if name in entities_to_classify_set else "relations"
            _persist_annotation(cat, name, catalog[name])
        if batch_idx % max(1, total_a // 4) == 0 or batch_idx == total_a:
            t_last = _progress("annotate", batch_idx, total_a, t_last)

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
