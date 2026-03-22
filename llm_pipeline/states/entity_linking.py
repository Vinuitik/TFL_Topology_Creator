from __future__ import annotations

"""Merge duplicate mentions into canonical entity identities."""

from collections import defaultdict

from schemas import CanonicalEntity, PipelineState


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def run_entity_linking(state: PipelineState) -> PipelineState:
    entities = state.get("entities", [])
    if not entities:
        return {"canonical_entities": []}

    grouped = defaultdict(list)
    for ent in entities:
        mention = ent.mentions[0] if ent.mentions else ent.id
        grouped[_normalize_name(mention)].append(mention)

    canonical_entities = []
    for idx, (key, aliases) in enumerate(grouped.items(), start=1):
        canonical_name = sorted(aliases, key=len)[-1]
        canonical_entities.append(
            CanonicalEntity(
                id=f"cent_{idx}",
                canonical_name=canonical_name,
                type="NamedEntity",
                aliases=sorted(set(aliases)),
                confidence=0.85,
            )
        )

    return {"canonical_entities": canonical_entities}
