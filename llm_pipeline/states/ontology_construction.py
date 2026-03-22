from __future__ import annotations

"""Convert mapped schema data into triple-like ontology statements."""

from schemas import PipelineState


def run_ontology_construction(state: PipelineState) -> PipelineState:
    mapped = state.get("mapped_graph", {})

    triples = []
    for class_item in mapped.get("classes", []):
        triples.append(
            {
                "subject": class_item["id"],
                "predicate": "rdf:type",
                "object": class_item["class"],
            }
        )

    for prop in mapped.get("object_properties", []):
        triples.append(
            {
                "subject": prop["subject"],
                "predicate": prop["predicate"],
                "object": prop["object"],
            }
        )

    for prop in mapped.get("data_properties", []):
        triples.append(
            {
                "subject": prop["entity"],
                "predicate": prop["key"],
                "object": prop["value"],
            }
        )

    return {"ontology_draft": {"triples": triples}}
