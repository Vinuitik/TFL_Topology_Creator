from __future__ import annotations

"""Classify entities as class/individual and relations as object/datatype property,
then generate rdfs:label and rdfs:comment for each via the lightweight entity model.
Runs after entity_linking, before schema_mapping.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List

import redis

from schemas import PipelineState
from service.llm import call_llm

log = logging.getLogger(__name__)

_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL")
_BATCH = 15
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

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
        json.dumps({"kind": entry["kind"], "label": entry["label"], "comment": entry["comment"]}),
    )

_VALID_ENTITY_KINDS = {"class", "individual"}
_VALID_RELATION_KINDS = {"object_property", "datatype_property"}


def _is_literal(value: str) -> bool:
    cleaned = value.strip()
    return bool(re.fullmatch(r"-?\d+", cleaned) or re.fullmatch(r"-?\d+\.\d+", cleaned))


def _run_batch(state_name: str, names: List[str]) -> List[Dict[str, str]]:
    params = "\n" + "\n".join(f'{i + 1}. "{n}"' for i, n in enumerate(names)) + "\n"
    try:
        result = call_llm(state_name, params, model=_ENTITY_MODEL)
        results = result.get("results", [])
        if len(results) < len(names):
            results.extend([{}] * (len(names) - len(results)))
        return results[: len(names)]
    except Exception as exc:
        log.warning("%s batch failed: %s", state_name, exc)
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

    entity_names = sorted({
        name
        for t in triplets
        for name in (t.subject, t.object)
        if not _is_literal(name)
    })
    relation_names = sorted({t.predicate for t in triplets})

    catalog: Dict[str, Dict[str, Any]] = {}

    # Load already-annotated entries from Redis; collect what still needs LLM work.
    entities_to_classify: List[str] = []
    for name in entity_names:
        hit = _load_annotation("entities", name)
        if hit:
            catalog[name] = hit
        else:
            entities_to_classify.append(name)

    relations_to_classify: List[str] = []
    for name in relation_names:
        hit = _load_annotation("relations", name)
        if hit:
            catalog[name] = hit
        else:
            relations_to_classify.append(name)

    log.info(
        "entity_classification: cache hits — entities=%d/%d relations=%d/%d",
        len(entity_names) - len(entities_to_classify), len(entity_names),
        len(relation_names) - len(relations_to_classify), len(relation_names),
    )

    # Step 1: classify new entities
    for i in range(0, len(entities_to_classify), _BATCH):
        batch = entities_to_classify[i : i + _BATCH]
        results = _run_batch("entity_classify", batch)
        for name, r in zip(batch, results):
            kind = r.get("type", "individual")
            if kind not in _VALID_ENTITY_KINDS:
                kind = "individual"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}

    # Step 2: classify new relations
    for i in range(0, len(relations_to_classify), _BATCH):
        batch = relations_to_classify[i : i + _BATCH]
        results = _run_batch("relation_classify", batch)
        for name, r in zip(batch, results):
            kind = r.get("type", "object_property")
            if kind not in _VALID_RELATION_KINDS:
                kind = "object_property"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}

    # Step 3: annotate only newly classified items (cached ones already have label+comment)
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
        "entity_classification: %d entities (%d class, %d individual), %d relations",
        len(entity_names),
        sum(1 for n in entity_names if catalog.get(n, {}).get("kind") == "class"),
        sum(1 for n in entity_names if catalog.get(n, {}).get("kind") == "individual"),
        len(relation_names),
    )

    return {"entity_catalog": catalog}
