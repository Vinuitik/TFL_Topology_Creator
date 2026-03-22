from __future__ import annotations

"""Create relation edges between entities and flag weak/missing relations."""

from schemas import PipelineState, Relation


def run_relation_extraction(state: PipelineState) -> PipelineState:
    canonical_entities = state.get("canonical_entities", [])
    normalized = state.get("normalized_document")

    if not canonical_entities or normalized is None:
        return {"relations": [], "missing_relations": True}

    relations = []
    sentences = normalized.sentences
    if len(canonical_entities) >= 2:
        relations.append(
            Relation(
                id="rel_1",
                subject_id=canonical_entities[0].id,
                predicate="related_to",
                object_id=canonical_entities[1].id,
                confidence=0.7,
                provenance_sentence=sentences[0] if sentences else "",
            )
        )

    return {
        "relations": relations,
        "missing_relations": len(relations) == 0,
        "low_confidence": any(r.confidence < 0.6 for r in relations),
    }
