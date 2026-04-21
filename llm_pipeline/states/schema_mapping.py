from __future__ import annotations

"""Map linked triplets into ontology-aligned nodes and edges."""

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from schemas import PipelineState


_BASE_NS = "urn:webprotege:ontology:c73d2ce1-09f8-451b-b6fd-d3ba1ee14c49#"
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


# WebProtege UUID IRIs from KE_CW2_Ontology.ttl — these are the canonical IRIs
# that must be used so pipeline triples are in the same property space as the
# seed individuals already defined in the base ontology.
_WP = "http://webprotege.stanford.edu/"


def _default_predicate_catalog() -> List[Dict[str, str]]:
    """All predicates defined in the TFL ontology (KE_CW2_Ontology.ttl).

    Priority entries use the EXACT WebProtege UUID IRIs from the base ontology
    so that SPARQL queries against properties like :hasStop, :hasZone,
    :servedByLine work correctly. Fuzzy-match fallbacks follow.
    """
    return [
        # ── EXACT UUID IRIs from KE_CW2_Ontology.ttl ────────────────────────
        # These must come FIRST so fuzzy matching always prefers them.
        {"label": "has stop",                      "iri": f"{_WP}R5vX3rRQHCFUQRqsCJpU7U"},   # hasStop
        {"label": "connection line",               "iri": f"{_WP}R7jFYnKUCHBZlrbM3lXqSCf"},  # connectionLine
        {"label": "has transport mode",            "iri": f"{_WP}R7v2UJSR5VRm9sY5m9mhjoD"},  # hasTransportMode
        {"label": "has fare",                      "iri": f"{_WP}RBF7bBYX8buEHB8SURG8bAt"},  # hasFare
        {"label": "offers accessibility feature",  "iri": f"{_WP}RBcEVIqolJplXGnyvK1Sg68"},  # offersAccessibilityFeature
        {"label": "served by line",               "iri": f"{_WP}RCCYxhe5VfhDbpzKCYZDdJM"},  # servedByLine
        {"label": "directly connected to",         "iri": f"{_WP}RCMwEsdqyKGYIXWhK3cknWo"},  # directlyConnectedTo
        {"label": "provides service",              "iri": f"{_WP}RJAwTY1EBQrdbPNMCkPZE0"},   # providesService
        {"label": "start station",                 "iri": f"{_WP}RObdgWrfvP7lOibVufoCGj"},   # startStation
        {"label": "end station",                   "iri": f"{_WP}Rhira9cILzBTmJrEsO00c5"},   # endStation
        # BASE_NS properties
        {"label": "has zone",                      "iri": f"{_BASE_NS}hasZone"},
        {"label": "end zone",                      "iri": f"{_BASE_NS}endZone"},
        {"label": "start zone",                    "iri": f"{_BASE_NS}startZone"},
        {"label": "belongs to route",              "iri": f"{_BASE_NS}belongsToRoute"},
        {"label": "sequence stop",                 "iri": f"{_BASE_NS}sequenceStop"},
        {"label": "has name",                      "iri": f"{_BASE_NS}hasName"},
        {"label": "zone number",                   "iri": f"{_BASE_NS}zoneNumber"},
        {"label": "stop sequence number",          "iri": f"{_BASE_NS}stopSequenceNumber"},
        {"label": "fare cost",                     "iri": f"{_BASE_NS}fareCost"},
        # ── Fuzzy-match aliases (lower priority) ─────────────────────────────
        {"label": "serves",                        "iri": f"{_WP}R5vX3rRQHCFUQRqsCJpU7U"},   # → hasStop
        {"label": "stops at",                      "iri": f"{_WP}R5vX3rRQHCFUQRqsCJpU7U"},   # → hasStop
        {"label": "connected to",                  "iri": f"{_WP}RCMwEsdqyKGYIXWhK3cknWo"},  # → directlyConnectedTo
        {"label": "connects",                      "iri": f"{_WP}RCMwEsdqyKGYIXWhK3cknWo"},  # → directlyConnectedTo
        {"label": "located in zone",               "iri": f"{_BASE_NS}hasZone"},
        {"label": "located in",                    "iri": f"{_BASE_NS}hasZone"},
        {"label": "step free access",              "iri": f"{_WP}RBcEVIqolJplXGnyvK1Sg68"},  # → offersAccessibilityFeature
        {"label": "accessibility",                 "iri": f"{_WP}RBcEVIqolJplXGnyvK1Sg68"},  # → offersAccessibilityFeature
        {"label": "belongs to line",               "iri": f"{_BASE_NS}belongsToLine"},
        {"label": "part of",                       "iri": f"{_BASE_NS}belongsToLine"},
        {"label": "has start station",             "iri": f"{_WP}RObdgWrfvP7lOibVufoCGj"},
        {"label": "has end station",               "iri": f"{_WP}Rhira9cILzBTmJrEsO00c5"},
        {"label": "line length",                   "iri": f"{_BASE_NS}lineLength"},
        {"label": "opened in",                     "iri": f"{_BASE_NS}openedIn"},
        {"label": "inception",                     "iri": f"{_BASE_NS}openedIn"},
        {"label": "operated by",                   "iri": f"{_BASE_NS}operatedBy"},
        {"label": "operates",                      "iri": f"{_BASE_NS}operates"},
        {"label": "is tfl service",                "iri": f"{_BASE_NS}isTflService"},
        {"label": "is fare paying",                "iri": f"{_BASE_NS}isFarePaying"},
        {"label": "is scheduled service",          "iri": f"{_BASE_NS}isScheduledService"},
        {"label": "has penalty fare",              "iri": f"{_BASE_NS}hasPenaltyFare"},
        {"label": "has compensation right",        "iri": f"{_BASE_NS}hasCompensationRight"},
        {"label": "related to",                    "iri": f"{_BASE_NS}relatedTo"},
    ]


def _default_class_catalog() -> List[Dict[str, str]]:
    """All classes defined in KE_CW2_Ontology.ttl.

    Uses the EXACT WebProtege UUID IRIs for core classes so that individuals
    generated by the pipeline match what the SPARQL queries expect (e.g.
    ?station a TrainStation means the class IRI must be the WebProtege UUID).
    """
    return [
        # ── Access points (exact WebProtege UUID IRIs) ───────────────────────
        {"label": "Train Station",         "iri": f"{_WP}TrainStation"},
        {"label": "TrainStation",          "iri": f"{_WP}TrainStation"},
        {"label": "Station",               "iri": f"{_WP}TrainStation"},
        {"label": "Underground Station",   "iri": f"{_WP}TrainStation"},
        {"label": "Tube Station",          "iri": f"{_WP}TrainStation"},
        {"label": "Bus Stop",              "iri": f"{_WP}R9TCSglVMKeAj22qlxYUozU"},
        {"label": "BusStop",               "iri": f"{_WP}R9TCSglVMKeAj22qlxYUozU"},
        {"label": "Transit Access Point",  "iri": f"{_BASE_NS}TransitAccessPoint"},
        {"label": "TransitAccessPoint",    "iri": f"{_BASE_NS}TransitAccessPoint"},
        {"label": "Interchange Station",   "iri": f"{_BASE_NS}InterchangeStation"},
        {"label": "InterchangeStation",    "iri": f"{_BASE_NS}InterchangeStation"},
        {"label": "Interchange",           "iri": f"{_BASE_NS}InterchangeStation"},
        # ── Network (exact WebProtege UUID IRIs) ─────────────────────────────
        {"label": "Line",                  "iri": f"{_WP}RDEVnVTugRbS0jlPdGiumAj"},
        {"label": "Underground Line",      "iri": f"{_WP}RDEVnVTugRbS0jlPdGiumAj"},
        {"label": "Route",                 "iri": f"{_WP}RIfSnBzsdC7fyIHQcX6Erd"},
        {"label": "Bus Route",             "iri": f"{_WP}RIfSnBzsdC7fyIHQcX6Erd"},
        {"label": "RouteStopSequence",     "iri": f"{_BASE_NS}RouteStopSequence"},
        # ── Fares / zones (exact WebProtege UUID IRIs) ───────────────────────
        {"label": "Zone",                  "iri": f"{_WP}R7cZlQsX1sMesyLmlHKw2lg"},
        {"label": "Fare Zone",             "iri": f"{_WP}R7cZlQsX1sMesyLmlHKw2lg"},
        {"label": "Fare",                  "iri": f"{_WP}RFQBoIMyODKarwW9fBl0aS"},
        {"label": "Peak Fare",             "iri": f"{_BASE_NS}PeakFare"},
        {"label": "Off Peak Fare",         "iri": f"{_BASE_NS}OffPeakFare"},
        # ── Journey (exact WebProtege UUID IRI) ──────────────────────────────
        {"label": "Journey",               "iri": f"{_WP}R8gcQaW839Or2hVYprhpSK8"},
        # ── Operations ───────────────────────────────────────────────────────
        {"label": "Transport Mode",        "iri": f"{_WP}R7mQXjcxy79h9g8J1fC0tjV"},
        {"label": "TransportMode",         "iri": f"{_WP}R7mQXjcxy79h9g8J1fC0tjV"},
        # ── Accessibility ─────────────────────────────────────────────────────
        {"label": "Accessibility Feature", "iri": f"{_WP}R8suZp8urh3QUp7Gjq7I9vS"},
        {"label": "AccessibilityFeature",  "iri": f"{_WP}R8suZp8urh3QUp7Gjq7I9vS"},
        {"label": "Step Free Access",      "iri": f"{_WP}R8suZp8urh3QUp7Gjq7I9vS"},
        # ── Passenger rights ──────────────────────────────────────────────────
        {"label": "Ticket",                "iri": f"{_BASE_NS}Ticket"},
        {"label": "Passenger Right",       "iri": f"{_BASE_NS}PassengerRight"},
        {"label": "Regulation",            "iri": f"{_BASE_NS}Regulation"},
        # ── Fallback ──────────────────────────────────────────────────────────
        {"label": "TransportEntity",       "iri": f"{_BASE_NS}TransitAccessPoint"},
        {"label": "Service",               "iri": f"{_WP}RDEVnVTugRbS0jlPdGiumAj"},
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
                "iri": f"{_BASE_NS}{_slug(label)}",
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
            pred_iri = f"{_BASE_NS}{_slug(t.predicate)}"
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
            edge["predicate_kind"] = "datatype_property"  # FORCE DATATYPE OVERRIDE
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
