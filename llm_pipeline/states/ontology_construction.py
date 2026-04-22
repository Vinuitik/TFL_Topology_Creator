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

    # --- Ontology header ---
    _ONTOLOGY_IRI = "http://example.org/tfl/extracted"
    _OWL_IMPORTS = "http://www.w3.org/2002/07/owl#imports"
    _BASE_ONTOLOGY = "http://example.org/tfl"
    _add(triples, _ONTOLOGY_IRI, _RDF_TYPE, "http://www.w3.org/2002/07/owl#Ontology")
    _add(triples, _ONTOLOGY_IRI, _OWL_IMPORTS, _BASE_ONTOLOGY)

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

        stmt_iri = f"http://example.org/pt#stmt_{idx}"
        if edge.get("provenance_sentence"):
            _add(triples, stmt_iri, _PROV_FROM_TEXT, edge["provenance_sentence"], is_literal=True)

    return {"ontology_draft": {"triples": triples}}
