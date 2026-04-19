from __future__ import annotations

"""Classify entities as class/individual and relations as object/datatype property,
then generate rdfs:label and rdfs:comment for each via the lightweight entity model.
Runs after entity_linking, before schema_mapping.
"""

import logging
import os
import re
from typing import Any, Dict, List

from schemas import PipelineState
from service.llm import call_llm

log = logging.getLogger(__name__)

_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL", "qwen2.5:1.5b")
_BATCH = 15

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

    # Step 1: classify entities (class vs individual)
    for i in range(0, len(entity_names), _BATCH):
        batch = entity_names[i : i + _BATCH]
        results = _run_batch("entity_classify", batch)
        for name, r in zip(batch, results):
            kind = r.get("type", "individual")
            if kind not in _VALID_ENTITY_KINDS:
                kind = "individual"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}

    # Step 2: classify relations (object_property vs datatype_property)
    for i in range(0, len(relation_names), _BATCH):
        batch = relation_names[i : i + _BATCH]
        results = _run_batch("relation_classify", batch)
        for name, r in zip(batch, results):
            kind = r.get("type", "object_property")
            if kind not in _VALID_RELATION_KINDS:
                kind = "object_property"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}

    # Step 3: annotate all (label + comment)
    all_items = [{"name": n, "kind": catalog[n]["kind"]} for n in sorted(catalog)]
    for i in range(0, len(all_items), _BATCH):
        batch = all_items[i : i + _BATCH]
        results = _annotate_batch(batch)
        for item, r in zip(batch, results):
            name = item["name"]
            catalog[name]["label"] = r.get("label", name) or name
            catalog[name]["comment"] = r.get("comment", "") or ""

    log.info(
        "entity_classification: %d entities (%d class, %d individual), %d relations",
        len(entity_names),
        sum(1 for n in entity_names if catalog.get(n, {}).get("kind") == "class"),
        sum(1 for n in entity_names if catalog.get(n, {}).get("kind") == "individual"),
        len(relation_names),
    )

    return {"entity_catalog": catalog}
