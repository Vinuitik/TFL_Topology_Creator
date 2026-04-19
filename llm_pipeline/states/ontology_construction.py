from __future__ import annotations

"""Convert mapped graph data into ontology draft triples."""

from typing import Any, Dict, List

from schemas import PipelineState


_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
_OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"
_OWL_NAMED_INDIVIDUAL = "http://www.w3.org/2002/07/owl#NamedIndividual"
_OWL_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#ObjectProperty"
_OWL_DATATYPE_PROPERTY = "http://www.w3.org/2002/07/owl#DatatypeProperty"
_PROV_FROM_TEXT = "http://www.w3.org/ns/prov#value"


def _add(
    triples: List[Dict[str, Any]],
    subject: str,
    predicate: str,
    obj: str,
    is_literal: bool = False,
    datatype: str = "",
) -> None:
    row: Dict[str, Any] = {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "is_literal": is_literal,
    }
    if datatype:
        row["datatype"] = datatype
    triples.append(row)


def run_ontology_construction(state: PipelineState) -> PipelineState:
    mapped = state.get("mapped_graph", {})
    nodes = mapped.get("nodes", [])
    edges = mapped.get("edges", [])

    triples: List[Dict[str, Any]] = []

    # --- Classes ---
    seen_classes: set = set()
    for node in nodes:
        class_iri = node["class_iri"]
        if class_iri in seen_classes:
            continue
        seen_classes.add(class_iri)
        _add(triples, class_iri, _RDF_TYPE, _OWL_CLASS)
        _add(triples, class_iri, _RDFS_LABEL, node.get("class_label", ""), is_literal=True)
        # If the node itself IS the class, emit its comment too
        if node.get("is_class") and node.get("comment"):
            _add(triples, class_iri, _RDFS_COMMENT, node["comment"], is_literal=True)

    # --- Individuals ---
    for node in nodes:
        if node.get("is_class"):
            continue
        iri = node["iri"]
        _add(triples, iri, _RDF_TYPE, _OWL_NAMED_INDIVIDUAL)
        _add(triples, iri, _RDF_TYPE, node["class_iri"])
        _add(triples, iri, _RDFS_LABEL, node["label"], is_literal=True)
        if node.get("comment"):
            _add(triples, iri, _RDFS_COMMENT, node["comment"], is_literal=True)

    # --- Properties ---
    seen_predicates: set = set()
    for edge in edges:
        pred_iri = edge["predicate_iri"]
        if pred_iri in seen_predicates:
            continue
        seen_predicates.add(pred_iri)

        kind = edge.get("predicate_kind", "object_property")
        prop_type = _OWL_DATATYPE_PROPERTY if kind == "datatype_property" else _OWL_OBJECT_PROPERTY
        _add(triples, pred_iri, _RDF_TYPE, prop_type)
        _add(triples, pred_iri, _RDFS_LABEL, edge["predicate_label"], is_literal=True)

        # Fetch comment from entity_catalog if available
        entity_catalog: Dict[str, Any] = state.get("entity_catalog", {})
        comment = entity_catalog.get(edge["predicate_label"], {}).get("comment", "")
        if not comment:
            # predicate_label may be the display label; try original canonical name via predicate_iri slug
            for name, entry in entity_catalog.items():
                if entry.get("label") == edge["predicate_label"]:
                    comment = entry.get("comment", "")
                    break
        if comment:
            _add(triples, pred_iri, _RDFS_COMMENT, comment, is_literal=True)

    # --- Relation triples ---
    for idx, edge in enumerate(edges, start=1):
        if "object_iri" in edge:
            _add(triples, edge["subject_iri"], edge["predicate_iri"], edge["object_iri"])
        else:
            _add(
                triples,
                edge["subject_iri"],
                edge["predicate_iri"],
                edge.get("object_literal", ""),
                is_literal=True,
                datatype=edge.get("object_datatype", ""),
            )

        stmt_iri = f"http://example.org/pt#stmt/{idx}"
        if edge.get("provenance_sentence"):
            _add(triples, stmt_iri, _PROV_FROM_TEXT, edge["provenance_sentence"], is_literal=True)

    return {"ontology_draft": {"triples": triples}}
