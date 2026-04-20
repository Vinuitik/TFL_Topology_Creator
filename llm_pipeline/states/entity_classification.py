from __future__ import annotations

"""Classify entities as class/individual and relations as object/datatype property,
then generate rdfs:label and rdfs:comment for each via the lightweight entity model.
Runs after entity_linking, before schema_mapping.
"""

import logging
import os
import re
from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor

from schemas import PipelineState
from service.llm import call_llm
import config

log = logging.getLogger(__name__)

_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL")

_VALID_ENTITY_KINDS = {"class", "individual"}
_VALID_RELATION_KINDS = {"object_property", "datatype_property"}


def _is_literal(value: str) -> bool:
    cleaned = value.strip().lower()
    # Booleans
    if cleaned in ("true", "false", "yes", "no"):
        return True
    # Numbers
    if re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return True
    # Dates/Years: "1950", "1950s", "3 july 1939", "september 1939"
    if re.fullmatch(r"\d{4}s?", cleaned):
        return True
    if re.fullmatch(r"(\d{1,2}\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}", cleaned):
        return True
    # Times / Durations: "60 mins", "2 hours"
    if re.search(r"^\d+\s*(mins?|minutes?|hrs?|hours?|seconds?|secs?)$", cleaned):
        return True
    return False


def _run_single(args: tuple[str, str]) -> Dict[str, str]:
    state_name, name = args
    params = f'\nname="{name}"\n'
    try:
        result = call_llm(state_name, params, model=_ENTITY_MODEL)
        return result
    except Exception as exc:
        log.warning("%s failed for %r: %s", state_name, name, exc)
        return {}


def _annotate_single(item: Dict[str, str]) -> Dict[str, str]:
    params = f'\nname="{item["name"]}" type="{item["kind"]}"\n'
    try:
        result = call_llm("entity_annotate", params, model=_ENTITY_MODEL)
        return result
    except Exception as exc:
        log.warning("entity_annotate failed for %r: %s", item["name"], exc)
        return {}


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

    with ThreadPoolExecutor(max_workers=config.LLM_MAX_CONCURRENCY) as executor:
        # Step 1: classify entities (class vs individual)
        args_ent = [("entity_classify", name) for name in entity_names]
        ent_results = list(executor.map(_run_single, args_ent))
        for name, r in zip(entity_names, ent_results):
            kind = r.get("type", "individual")
            if kind not in _VALID_ENTITY_KINDS:
                kind = "individual"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}

        # Step 2: classify relations (object_property vs datatype_property)
        args_rel = [("relation_classify", name) for name in relation_names]
        rel_results = list(executor.map(_run_single, args_rel))
        for name, r in zip(relation_names, rel_results):
            kind = r.get("type", "object_property")
            if kind not in _VALID_RELATION_KINDS:
                kind = "object_property"
            catalog[name] = {"kind": kind, "label": name, "comment": ""}

        # Step 3: annotate all (label + comment)
        all_items = [{"name": n, "kind": catalog[n]["kind"]} for n in sorted(catalog)]
        ann_results = list(executor.map(_annotate_single, all_items))
        for item, r in zip(all_items, ann_results):
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
