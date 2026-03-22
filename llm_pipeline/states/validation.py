from __future__ import annotations

"""Validate ontology health and emit errors for possible reruns."""

from schemas import PipelineState


def run_validation(state: PipelineState) -> PipelineState:
    inferred = state.get("inferred_ontology", {"triples": []})
    triples = inferred.get("triples", [])

    errors = []
    if not triples:
        errors.append("Ontology contains no triples.")

    has_relation = any(t.get("predicate") not in {"rdf:type"} for t in triples)
    if not has_relation:
        errors.append("No object/data relations found.")

    failed_validation = len(errors) > 0
    iteration = state.get("iteration", 0) + 1

    return {
        "validated_ontology": inferred,
        "validation_errors": errors,
        "failed_validation": failed_validation,
        "iteration": iteration,
    }
