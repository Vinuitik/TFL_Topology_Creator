from __future__ import annotations

"""Map extracted items into ontology-aligned schema buckets."""

from schemas import PipelineState


def run_schema_mapping(state: PipelineState) -> PipelineState:
    canonical_entities = state.get("canonical_entities", [])
    relations = state.get("relations", [])
    attributes = state.get("attributes", [])

    mapped = {
        "classes": [
            {"id": ent.id, "class": ent.type, "label": ent.canonical_name}
            for ent in canonical_entities
        ],
        "object_properties": [
            {
                "id": rel.id,
                "subject": rel.subject_id,
                "predicate": rel.predicate,
                "object": rel.object_id,
            }
            for rel in relations
        ],
        "data_properties": [
            {
                "id": attr.id,
                "entity": attr.entity_id,
                "key": attr.key,
                "value": attr.value,
                "datatype": attr.datatype,
            }
            for attr in attributes
        ],
    }

    return {"mapped_graph": mapped}
