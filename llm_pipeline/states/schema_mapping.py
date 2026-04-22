from __future__ import annotations

"""Map linked triplets into ontology-aligned nodes and edges."""

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from schemas import PipelineState
from .entity_classification import _is_literal


_BASE_NS = "http://example.org/tfl#"
_XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
_XSD_DECIMAL = "http://www.w3.org/2001/XMLSchema#decimal"
_XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"
_XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"
_XSD_TIME = "http://www.w3.org/2001/XMLSchema#time"


def _slug(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return out or "item"


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


_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
_XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"

def _literal_value(value: str) -> Tuple[str, str] | None:
    cleaned = value.strip().lower()
    if cleaned in ("true", "false", "yes", "no"):
        return ("true" if cleaned in ("true", "yes") else "false"), _XSD_BOOLEAN
    if re.fullmatch(r"-?\d+", cleaned):
        return cleaned, _XSD_INTEGER
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        return cleaned, _XSD_DECIMAL
    if re.fullmatch(r"\d{4}[-_]\d{2}[-_]\d{2}", cleaned):
        return value.strip().replace("_", "-"), _XSD_DATE
    if re.fullmatch(r"\d{4}[-_]\d{2}[-_]\d{2}t\d{2}:\d{2}:\d{2}(\.\d+)?z?", cleaned):
        return value.strip().replace("_", "-").upper(), _XSD_DATETIME
    if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", cleaned):
        return value.strip(), _XSD_TIME
    if re.fullmatch(r"\d{4}s?", cleaned):
        return value.strip(), _XSD_STRING
    if re.fullmatch(r"(\d{1,2}\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}", cleaned):
        return value.strip(), _XSD_STRING
    if re.search(r"^\d+\s*(mins?|minutes?|hrs?|hours?|seconds?|secs?)$", cleaned):
        return value.strip(), _XSD_STRING
    if re.fullmatch(r"zone\s+\d+(-?\d+)?", cleaned):
        return value.strip(), _XSD_STRING
    return None


# WebProtege UUID IRIs from KE_CW2_Ontology.ttl — these are the canonical IRIs
# that must be used so pipeline triples are in the same property space as the
# seed individuals already defined in the base ontology.
_WP = "http://webprotege.stanford.edu/"


def _default_predicate_catalog() -> List[Dict[str, str]]:
    """Strictly return nothing here; relying on rag_catalog populated from final_ontology.ttl."""
    return []


def _default_class_catalog() -> List[Dict[str, str]]:
    """Strictly return nothing here; relying on rag_catalog populated from final_ontology.ttl."""
    return []


def run_schema_mapping(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return {"mapped_graph": {"nodes": [], "edges": [], "unmapped_predicates": []}}

    rag_catalog = state.get("rag_catalog", {})
    entity_catalog: Dict[str, Any] = state.get("entity_catalog", {})

    predicate_catalog = list(rag_catalog.get("predicates", [])) + _default_predicate_catalog()
    class_catalog = list(rag_catalog.get("classes", [])) + _default_class_catalog()

    # 1. Pre-map predicates for quick lookup
    catalog_preds = {p["iri"]: p for p in rag_catalog.get("predicates", [])}
    label_to_iri = {p["label"]: p["iri"] for p in rag_catalog.get("predicates", [])}
    label_to_iri.update({c["label"]: c["iri"] for c in rag_catalog.get("classes", [])})
    
    datatype_preds = {iri for iri, p in catalog_preds.items() if p.get("property_type") == "datatype_property"}

    # 2. Identify all entities (subjects + objects that aren't literals)
    # We must be careful: if a predicate is known to be an ObjectProperty, 
    # its object IS an entity even if it looks like a literal (e.g., "true").
    entity_set = {t.subject for t in triplets}
    for t in triplets:
        pred_match, _ = _best_match(t.predicate, predicate_catalog)
        p_iri = pred_match["iri"] if pred_match else None
        
        # If the catalog says it's a DatatypeProperty, the object is NOT an entity.
        if p_iri and p_iri in datatype_preds:
            continue
            
        # If it's unmapped or an ObjectProperty, check if it's a literal.
        # But if it's an ObjectProperty, we treat it as an entity regardless.
        if p_iri and catalog_preds.get(p_iri, {}).get("property_type") == "object_property":
            entity_set.add(t.object)
        elif _literal_value(t.object) is None:
            entity_set.add(t.object)

    entity_labels = sorted(entity_set)

    # 3. Build Node Map
    node_map: Dict[str, Dict[str, Any]] = {}
    for idx, label in enumerate(entity_labels, start=1):
        cat = entity_catalog.get(label, {})
        display_label = cat.get("label", label)
        comment = cat.get("comment", "")
        existing_iri = label_to_iri.get(label)
        
        class_match, class_score = _best_match(label, class_catalog)
        if class_match and class_score >= 0.4:
            class_iri = class_match["iri"]
            class_label = class_match["label"]
        else:
            class_iri = f"{_BASE_NS}TransitAccessPoint"
            class_label = "TransitAccessPoint"

        node_map[label] = {
            "id": f"ent_{idx}",
            "label": display_label,
            "comment": comment,
            "iri": existing_iri if existing_iri else f"{_BASE_NS}{_slug(label)}",
            "class_iri": class_iri,
            "class_label": class_label,
            "is_class": False,
            "is_literal": False, # These are all entities
        }

    edges: List[Dict[str, Any]] = []
    unmapped_predicates: List[str] = []

    for t in triplets:
        cat = entity_catalog.get(t.predicate, {})
        display_pred_label = cat.get("label", t.predicate)

        pred_match, pred_score = _best_match(t.predicate, predicate_catalog)
        if pred_match and pred_score >= 0.5:
            pred_iri = pred_match["iri"]
        else:
            pred_iri = f"{_BASE_NS}{_slug(t.predicate)}"
            unmapped_predicates.append(t.predicate)

        obj_literal = _literal_value(t.object)
        
        edge: Dict[str, Any] = {
            "subject_id": node_map[t.subject]["id"],
            "subject_iri": node_map[t.subject]["iri"],
            "predicate_label": display_pred_label,
            "predicate_iri": pred_iri,
            "provenance_sentence": t.provenance_sentence,
        }

        # Value Type Enforcement
        p_type = catalog_preds.get(pred_iri, {}).get("property_type")

        if p_type == "datatype_property":
            # Force Literal
            val, dtype = obj_literal if obj_literal else (t.object, _XSD_STRING)
            edge["object_literal"] = val
            edge["object_datatype"] = dtype
            edge["predicate_kind"] = "datatype_property"
        
        elif p_type == "object_property":
            # Force IRI
            if t.object in node_map:
                edge["object_id"] = node_map[t.object]["id"]
                edge["object_iri"] = node_map[t.object]["iri"]
            else:
                # Fallback: slugify the literal into an individual
                edge["object_id"] = f"lit_{_slug(t.object)}"
                edge["object_iri"] = f"{_BASE_NS}{_slug(t.object)}"
            edge["predicate_kind"] = "object_property"
            
        else:
            # Unmapped heuristic
            if obj_literal:
                edge["object_literal"] = obj_literal[0]
                edge["object_datatype"] = obj_literal[1]
                edge["predicate_kind"] = "datatype_property"
            else:
                if t.object in node_map:
                    edge["object_id"] = node_map[t.object]["id"]
                    edge["object_iri"] = node_map[t.object]["iri"]
                else:
                    edge["object_id"] = f"lit_{_slug(t.object)}"
                    edge["object_iri"] = f"{_BASE_NS}{_slug(t.object)}"
                edge["predicate_kind"] = "object_property"

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
