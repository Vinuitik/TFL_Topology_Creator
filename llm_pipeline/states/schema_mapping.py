from __future__ import annotations

"""Map linked triplets into ontology-aligned nodes and edges."""

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from schemas import PipelineState


_BASE_NS = "http://example.org/tfl#"
_XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
_XSD_DECIMAL = "http://www.w3.org/2001/XMLSchema#decimal"


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
        return cleaned, _XSD_BOOLEAN
    if re.fullmatch(r"-?\d+", cleaned):
        return cleaned, _XSD_INTEGER
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        return cleaned, _XSD_DECIMAL
    if re.fullmatch(r"\d{4}s?", cleaned):
        return value.strip(), _XSD_STRING
    if re.fullmatch(r"(\d{1,2}\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}", cleaned):
        return value.strip(), _XSD_STRING
    if re.search(r"^\d+\s*(mins?|minutes?|hrs?|hours?|seconds?|secs?)$", cleaned):
        return value.strip(), _XSD_STRING
    return None


def _default_predicate_catalog() -> List[Dict[str, str]]:
    """All predicates defined in the TFL ontology (KE_CW2_Ontology.ttl).

    Labels are written in human-readable form so difflib.SequenceMatcher
    can fuzzy-match against REBEL output predicates like "served by line",
    "located in zone", "directly connected to", etc.
    """
    return [
        # ── Topology ────────────────────────────────────────────────────────
        {"label": "served by line",               "iri": f"{_BASE_NS}servedByLine"},
        {"label": "directly connected to",         "iri": f"{_BASE_NS}directlyConnectedTo"},
        {"label": "located in zone",               "iri": f"{_BASE_NS}locatedInZone"},
        {"label": "has zone",                      "iri": f"{_BASE_NS}hasZone"},
        {"label": "has stop",                      "iri": f"{_BASE_NS}hasStop"},
        {"label": "is interchange",                "iri": f"{_BASE_NS}isInterchange"},
        {"label": "connection line",               "iri": f"{_BASE_NS}connectionLine"},
        {"label": "has transport mode",            "iri": f"{_BASE_NS}hasTransportMode"},
        {"label": "belongs to line",               "iri": f"{_BASE_NS}belongsToLine"},
        {"label": "has start station",             "iri": f"{_BASE_NS}hasStartStation"},
        {"label": "has end station",               "iri": f"{_BASE_NS}hasEndStation"},
        {"label": "start station",                 "iri": f"{_BASE_NS}startStation"},
        {"label": "end station",                   "iri": f"{_BASE_NS}endStation"},
        {"label": "start zone",                    "iri": f"{_BASE_NS}startZone"},
        {"label": "end zone",                      "iri": f"{_BASE_NS}endZone"},
        {"label": "provides service",              "iri": f"{_BASE_NS}providesService"},
        {"label": "offers accessibility feature",  "iri": f"{_BASE_NS}offersAccessibilityFeature"},
        {"label": "has fare",                      "iri": f"{_BASE_NS}hasFare"},
        {"label": "fare amount",                   "iri": f"{_BASE_NS}fareAmount"},
        {"label": "part of",                       "iri": f"{_BASE_NS}belongsToLine"},
        {"label": "serves",                        "iri": f"{_BASE_NS}hasStop"},
        {"label": "connected to",                  "iri": f"{_BASE_NS}directlyConnectedTo"},
        {"label": "located in",                    "iri": f"{_BASE_NS}locatedInZone"},
        {"label": "line length",                   "iri": f"{_BASE_NS}lineLength"},
        {"label": "opened in",                     "iri": f"{_BASE_NS}openedIn"},
        {"label": "inception",                     "iri": f"{_BASE_NS}openedIn"},
        {"label": "start time",                    "iri": f"{_BASE_NS}openedIn"},
        # ── Operations ──────────────────────────────────────────────────────
        {"label": "operated by",                   "iri": f"{_BASE_NS}operatedBy"},
        {"label": "operates",                      "iri": f"{_BASE_NS}operates"},
        {"label": "is tfl service",                "iri": f"{_BASE_NS}isTflService"},
        {"label": "is fare paying",                "iri": f"{_BASE_NS}isFarePaying"},
        {"label": "is scheduled service",          "iri": f"{_BASE_NS}isScheduledService"},
        {"label": "has frequency",                 "iri": f"{_BASE_NS}hasFrequency"},
        {"label": "has capacity",                  "iri": f"{_BASE_NS}hasCapacity"},
        {"label": "runs",                          "iri": f"{_BASE_NS}operates"},
        {"label": "replaced by",                   "iri": f"{_BASE_NS}replacedBy"},
        {"label": "has name",                      "iri": f"{_BASE_NS}hasName"},
        {"label": "has zone number",               "iri": f"{_BASE_NS}hasZoneNumber"},
        # ── Passenger rights ────────────────────────────────────────────────
        {"label": "applies to",                    "iri": f"{_BASE_NS}appliesTo"},
        {"label": "eligible for refund",           "iri": f"{_BASE_NS}eligibleForRefund"},
        {"label": "has penalty fare",              "iri": f"{_BASE_NS}hasPenaltyFare"},
        {"label": "has penalty fare amount",       "iri": f"{_BASE_NS}hasPenaltyFareAmount"},
        {"label": "has compensation right",        "iri": f"{_BASE_NS}hasCompensationRight"},
        # ── General ─────────────────────────────────────────────────────────
        {"label": "related to",                    "iri": f"{_BASE_NS}relatedTo"},
    ]


def _default_class_catalog() -> List[Dict[str, str]]:
    """All classes defined in KE_CW2_Ontology.ttl under http://example.org/tfl#."""
    return [
        # ── Access points ───────────────────────────────────────────────────
        {"label": "Transit Access Point", "iri": f"{_BASE_NS}TransitAccessPoint"},
        {"label": "TransitAccessPoint",   "iri": f"{_BASE_NS}TransitAccessPoint"},
        {"label": "Train Station",         "iri": f"{_BASE_NS}TrainStation"},
        {"label": "TrainStation",          "iri": f"{_BASE_NS}TrainStation"},
        {"label": "Station",               "iri": f"{_BASE_NS}TrainStation"},
        {"label": "Bus Stop",              "iri": f"{_BASE_NS}BusStop"},
        {"label": "BusStop",               "iri": f"{_BASE_NS}BusStop"},
        # ── Network ─────────────────────────────────────────────────────────
        {"label": "Line",                  "iri": f"{_BASE_NS}Line"},
        {"label": "Route",                 "iri": f"{_BASE_NS}Route"},
        {"label": "Route Segment",         "iri": f"{_BASE_NS}RouteSegment"},
        {"label": "RouteSegment",          "iri": f"{_BASE_NS}RouteSegment"},
        # ── Fares / zones ───────────────────────────────────────────────────
        {"label": "Zone",                  "iri": f"{_BASE_NS}Zone"},
        {"label": "Fare Zone",             "iri": f"{_BASE_NS}Zone"},
        {"label": "Fare",                  "iri": f"{_BASE_NS}Fare"},
        # ── Journey ─────────────────────────────────────────────────────────
        {"label": "Journey",               "iri": f"{_BASE_NS}Journey"},
        # ── Operations ──────────────────────────────────────────────────────
        {"label": "Transport Mode",        "iri": f"{_BASE_NS}TransportMode"},
        {"label": "TransportMode",         "iri": f"{_BASE_NS}TransportMode"},
        {"label": "Operator",              "iri": f"{_BASE_NS}Operator"},
        # ── Accessibility ────────────────────────────────────────────────────
        {"label": "Accessibility Feature", "iri": f"{_BASE_NS}AccessibilityFeature"},
        {"label": "AccessibilityFeature",  "iri": f"{_BASE_NS}AccessibilityFeature"},
        # ── Passenger rights ─────────────────────────────────────────────────
        {"label": "Ticket",                "iri": f"{_BASE_NS}Ticket"},
        {"label": "Passenger Right",       "iri": f"{_BASE_NS}PassengerRight"},
        {"label": "PassengerRight",        "iri": f"{_BASE_NS}PassengerRight"},
        {"label": "Penalty Fare Policy",   "iri": f"{_BASE_NS}PenaltyFarePolicy"},
        {"label": "PenaltyFarePolicy",     "iri": f"{_BASE_NS}PenaltyFarePolicy"},
        {"label": "Regulation",            "iri": f"{_BASE_NS}Regulation"},
        # ── Fallback ─────────────────────────────────────────────────────────
        {"label": "TransportEntity",       "iri": f"{_BASE_NS}TransitAccessPoint"},
        {"label": "Service",               "iri": f"{_BASE_NS}Line"},
    ]


def run_schema_mapping(state: PipelineState) -> PipelineState:
    triplets = state.get("triplets", [])
    if not triplets:
        return {"mapped_graph": {"nodes": [], "edges": [], "unmapped_predicates": []}}

    rag_catalog = state.get("rag_catalog", {})
    entity_catalog: Dict[str, Any] = state.get("entity_catalog", {})

    predicate_catalog = list(rag_catalog.get("predicates", [])) + _default_predicate_catalog()
    class_catalog = list(rag_catalog.get("classes", [])) + _default_class_catalog()

    entity_set = {t.subject for t in triplets}
    for t in triplets:
        if _literal_value(t.object) is None:
            entity_set.add(t.object)
    entity_labels = sorted(entity_set)

    node_map: Dict[str, Dict[str, Any]] = {}
    for idx, label in enumerate(entity_labels, start=1):
        cat = entity_catalog.get(label, {})
        kind = cat.get("kind", "individual")
        display_label = cat.get("label", label)
        comment = cat.get("comment", "")

        if kind == "class":
            # Entity IS the class — IRI doubles as both instance and class IRI
            class_iri = f"{_BASE_NS}{_slug(label)}"
            node_map[label] = {
                "id": f"ent_{idx}",
                "label": display_label,
                "comment": comment,
                "iri": class_iri,
                "class_iri": class_iri,
                "class_label": display_label,
                "is_class": True,
            }
        else:
            # Individual — fuzzy-match to a class from the catalog
            class_match, class_score = _best_match(label, class_catalog)
            if class_match and class_score >= 0.6:
                class_iri = class_match["iri"]
                class_label = class_match["label"]
            else:
                class_iri = f"{_BASE_NS}TransportEntity"
                class_label = "TransportEntity"

            node_map[label] = {
                "id": f"ent_{idx}",
                "label": display_label,
                "comment": comment,
                "iri": f"{_BASE_NS}ent_{_slug(label)}",
                "class_iri": class_iri,
                "class_label": class_label,
                "is_class": False,
            }

    edges: List[Dict[str, Any]] = []
    unmapped_predicates: List[str] = []

    for t in triplets:
        cat = entity_catalog.get(t.predicate, {})
        display_pred_label = cat.get("label", t.predicate)

        pred_match, pred_score = _best_match(t.predicate, predicate_catalog)
        if pred_match and pred_score >= 0.66:
            pred_iri = pred_match["iri"]
        else:
            pred_iri = f"{_BASE_NS}rel_{_slug(t.predicate)}"
            unmapped_predicates.append(t.predicate)

        obj_literal = _literal_value(t.object)
        edge: Dict[str, Any] = {
            "subject_id": node_map[t.subject]["id"],
            "subject_iri": node_map[t.subject]["iri"],
            "predicate_label": display_pred_label,
            "predicate_iri": pred_iri,
            "predicate_kind": cat.get("kind", "object_property"),
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
