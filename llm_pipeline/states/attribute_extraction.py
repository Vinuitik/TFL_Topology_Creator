from __future__ import annotations

"""Extract datatype-like attributes and bind them to entities."""

import re

from schemas import Attribute, PipelineState


def run_attribute_extraction(state: PipelineState) -> PipelineState:
    normalized = state.get("normalized_document")
    canonical_entities = state.get("canonical_entities", [])
    if normalized is None or not canonical_entities:
        return {"attributes": []}

    attributes = []
    sentence = normalized.sentences[0] if normalized.sentences else ""
    for idx, entity in enumerate(canonical_entities, start=1):
        year_match = re.search(r"\b(19|20)\d{2}\b", sentence)
        if year_match:
            attributes.append(
                Attribute(
                    id=f"attr_{idx}",
                    entity_id=entity.id,
                    key="year",
                    value=year_match.group(0),
                    datatype="integer",
                    confidence=0.75,
                    provenance_sentence=sentence,
                )
            )

    return {"attributes": attributes}
