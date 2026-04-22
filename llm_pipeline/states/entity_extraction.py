from __future__ import annotations

"""Detect named entities and assign confidence scores."""

import re

from schemas import Entity, PipelineState


def run_entity_extraction(state: PipelineState) -> PipelineState:
    resolved = state.get("resolved_document")
    if resolved is None:
        return {}

    text = resolved.text
    mentions = sorted(set(re.findall(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\b", text)))

    entities = [
        Entity(
            id=f"ent_{idx + 1}",
            type="NamedEntity",
            mentions=[m],
            confidence=0.8,
        )
        for idx, m in enumerate(mentions)
    ]

    return {
        "entities": entities,
        "low_confidence": any(e.confidence < 0.6 for e in entities),
    }
