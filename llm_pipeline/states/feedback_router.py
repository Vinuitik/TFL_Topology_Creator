from __future__ import annotations

"""Route to end or rerun selected states when quality checks fail."""

from schemas import PipelineState


_MAX_ITERATIONS = 2


def route_after_validation(state: PipelineState) -> str:
    iteration = state.get("iteration", 0)
    if iteration >= _MAX_ITERATIONS:
        return "end"

    target = state.get("reroute_target")
    if target in {"coreference_resolution", "extraction", "entity_linking", "schema_mapping"}:
        return target

    if state.get("failed_validation"):
        return "entity_linking"

    if state.get("missing_relations"):
        return "extraction"

    if state.get("low_confidence"):
        return "coreference_resolution"

    return "end"
