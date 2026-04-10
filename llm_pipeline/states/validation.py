from __future__ import annotations

"""Validate ontology health and emit errors for possible reruns."""

from typing import Dict, List

from schemas import PipelineState


_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def _is_iri(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def run_validation(state: PipelineState) -> PipelineState:
    inferred = state.get("inferred_ontology", {"triples": []})
    triples = inferred.get("triples", [])
    mapping_unmapped = state.get("unmapped_predicates", [])

    errors: List[str] = []
    if not triples:
        errors.append("Ontology contains no triples.")

    has_relation = any(t.get("predicate") != _RDF_TYPE for t in triples)
    if not has_relation:
        errors.append("No object/data relations found.")

    iri_errors = 0
    for t in triples:
        s = t.get("subject", "")
        p = t.get("predicate", "")
        o = t.get("object", "")
        is_literal = bool(t.get("is_literal", False))

        if not _is_iri(s) or not _is_iri(p):
            iri_errors += 1
            continue
        if not is_literal and not _is_iri(o):
            iri_errors += 1

    if iri_errors:
        errors.append(f"IRI validation failed for {iri_errors} triples.")

    linking_conflicts = int(state.get("linking_conflicts", 0) or 0)
    if linking_conflicts > 0:
        errors.append(f"Linking consistency conflicts detected: {linking_conflicts}")

    failed_validation = len(errors) > 0
    iteration = state.get("iteration", 0) + 1

    reroute_target = "end"
    if failed_validation:
        if linking_conflicts > 0:
            reroute_target = "entity_linking"
        elif not has_relation:
            reroute_target = "extraction"

    report: Dict[str, object] = {
        "triple_count": len(triples),
        "has_relation": has_relation,
        "iri_errors": iri_errors,
        "unmapped_predicates": len(mapping_unmapped),
        "linking_conflicts": linking_conflicts,
    }

    return {
        "validated_ontology": inferred,
        "validation_errors": errors,
        "validation_report": report,
        "failed_validation": failed_validation,
        "missing_relations": not has_relation,
        "reroute_target": reroute_target,
        "iteration": iteration,
    }
