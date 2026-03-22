from __future__ import annotations

"""Add inferred facts on top of the draft ontology."""

from schemas import PipelineState


def run_reasoning(state: PipelineState) -> PipelineState:
    draft = state.get("ontology_draft", {"triples": []})
    triples = list(draft.get("triples", []))

    # Minimal inference: mark entities that have at least one relation as ConnectedEntity.
    subjects = {t["subject"] for t in triples if t.get("predicate") not in {"rdf:type"}}
    inferred = list(triples)
    for subj in subjects:
        inferred.append(
            {
                "subject": subj,
                "predicate": "rdf:type",
                "object": "ConnectedEntity",
            }
        )

    return {"inferred_ontology": {"triples": inferred}}
