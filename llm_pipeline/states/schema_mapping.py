from __future__ import annotations

"""Map linked triplets into ontology-aligned nodes and edges."""

import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

from schemas import PipelineState


_BASE_NS = "http://example.org/pt#"
_XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
_XSD_DECIMAL = "http://www.w3.org/2001/XMLSchema#decimal"


def _slug(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return out or "item"


def _label_from_iri(iri: str) -> str:
    token = iri.split("#")[-1].split("/")[-1]
    token = re.sub(r"[_-]+", " ", token)
    return token.strip() or iri


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _best_match(label: str, catalog: List[Dict[str, str]]) -> Tuple[Dict[str, str] | None, float]:
    target = _normalize_text(label)
    best = None
    best_score = 0.0
    for entry in catalog:
        cand = _normalize_text(entry.get("label", ""))
        score = SequenceMatcher(None, target, cand).ratio()
        if score > best_score:
            best = entry
            best_score = score
    return best, best_score


def _literal_value(value: str) -> Tuple[str, str] | None:
    cleaned = value.strip()
    if re.fullmatch(r"-?\d+", cleaned):
        return cleaned, _XSD_INTEGER
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        return cleaned, _XSD_DECIMAL
    return None


def _default_predicate_catalog() -> List[Dict[str, str]]:
    return [
        {"label": "operated by", "iri": f"{_BASE_NS}operatedBy"},
        {"label": "operates", "iri": f"{_BASE_NS}operates"},
        {"label": "applies to", "iri": f"{_BASE_NS}appliesTo"},
        {"label": "eligible for refund", "iri": f"{_BASE_NS}eligibleForRefund"},
        {"label": "has penalty fare", "iri": f"{_BASE_NS}hasPenaltyFare"},
        {"label": "has compensation right", "iri": f"{_BASE_NS}hasCompensationRight"},
        {"label": "related to", "iri": f"{_BASE_NS}relatedTo"},
    ]


def _default_class_catalog() -> List[Dict[str, str]]:
    return [
        {"label": "TransportEntity", "iri": f"{_BASE_NS}TransportEntity"},
        {"label": "Operator", "iri": f"{_BASE_NS}Operator"},
        {"label": "Service", "iri": f"{_BASE_NS}Service"},
        {"label": "Ticket", "iri": f"{_BASE_NS}Ticket"},
        {"label": "PassengerRight", "iri": f"{_BASE_NS}PassengerRight"},
        {"label": "PenaltyFarePolicy", "iri": f"{_BASE_NS}PenaltyFarePolicy"},
    ]


def run_schema_mapping(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return {"mapped_graph": {"nodes": [], "edges": [], "unmapped_predicates": []}}

    rag_catalog = state.get("rag_catalog", {})
    predicate_catalog = list(rag_catalog.get("predicates", [])) + _default_predicate_catalog()
    class_catalog = list(rag_catalog.get("classes", [])) + _default_class_catalog()

    entity_set = {t.subject for t in triplets}
    for t in triplets:
        if _literal_value(t.object) is None:
            entity_set.add(t.object)
    entity_labels = sorted(entity_set)
    node_map: Dict[str, Dict[str, str]] = {}
    for idx, label in enumerate(entity_labels, start=1):
        class_match, class_score = _best_match(label, class_catalog)
        if class_match and class_score >= 0.6:
            class_iri = class_match["iri"]
            class_label = class_match["label"]
        else:
            class_iri = f"{_BASE_NS}TransportEntity"
            class_label = "TransportEntity"

        ent_id = f"ent_{idx}"
        node_map[label] = {
            "id": ent_id,
            "label": label,
            "iri": f"{_BASE_NS}entity/{_slug(label)}",
            "class_iri": class_iri,
            "class_label": class_label,
        }

    edges: List[Dict[str, str]] = []
    unmapped_predicates: List[str] = []

    for t in triplets:
        pred_match, pred_score = _best_match(t.predicate, predicate_catalog)
        if pred_match and pred_score >= 0.66:
            pred_iri = pred_match["iri"]
            pred_label = pred_match["label"]
        else:
            pred_iri = f"{_BASE_NS}relation/{_slug(t.predicate)}"
            pred_label = t.predicate
            unmapped_predicates.append(t.predicate)

        obj_literal = _literal_value(t.object)
        edge: Dict[str, str] = {
            "subject_id": node_map[t.subject]["id"],
            "subject_iri": node_map[t.subject]["iri"],
            "predicate_label": pred_label,
            "predicate_iri": pred_iri,
            "confidence": str(t.confidence),
            "provenance_sentence": t.provenance_sentence,
        }

        if obj_literal is not None:
            edge["object_literal"] = obj_literal[0]
            edge["object_datatype"] = obj_literal[1]
        else:
            edge["object_id"] = node_map[t.object]["id"]
            edge["object_iri"] = node_map[t.object]["iri"]

        edges.append(edge)

    mapped = {
        "namespace": _BASE_NS,
        "nodes": list(node_map.values()),
        "edges": edges,
        "unmapped_predicates": sorted(set(unmapped_predicates)),
    }
    return {
        "mapped_graph": mapped,
        "unmapped_predicates": mapped["unmapped_predicates"],
    }
