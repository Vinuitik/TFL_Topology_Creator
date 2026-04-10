from __future__ import annotations

"""Convert mapped graph data into ontology draft triples."""

from typing import Dict, List

from schemas import PipelineState


_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_OWL_NAMED_INDIVIDUAL = "http://www.w3.org/2002/07/owl#NamedIndividual"
_PROV_FROM_TEXT = "http://www.w3.org/ns/prov#value"
_EX_CONFIDENCE = "http://example.org/pt#confidence"


def _add(triples: List[Dict[str, str]], subject: str, predicate: str, obj: str, is_literal: bool = False, datatype: str = "") -> None:
    row = {
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

    triples: List[Dict[str, str]] = []

    for node in nodes:
        _add(triples, node["iri"], _RDF_TYPE, _OWL_NAMED_INDIVIDUAL)
        _add(triples, node["iri"], _RDF_TYPE, node["class_iri"])
        _add(triples, node["iri"], _RDFS_LABEL, node["label"], is_literal=True)

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
        if edge.get("confidence"):
            _add(triples, stmt_iri, _EX_CONFIDENCE, edge["confidence"], is_literal=True)

    return {"ontology_draft": {"triples": triples}}
