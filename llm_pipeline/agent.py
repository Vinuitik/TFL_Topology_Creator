from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, StateGraph

from schemas import Document, PipelineState
from states import (
    route_after_validation,
    run_attribute_extraction,
    run_coreference_resolution,
    run_entity_extraction,
    run_entity_linking,
    run_input_ingestion,
    run_ontology_construction,
    run_reasoning,
    run_relation_extraction,
    run_schema_mapping,
    run_text_normalization,
    run_validation,
)


def build_graph() -> Any:
    graph = StateGraph(PipelineState)

    graph.add_node("input_ingestion", run_input_ingestion)
    graph.add_node("text_normalization", run_text_normalization)
    graph.add_node("coreference_resolution", run_coreference_resolution)
    graph.add_node("entity_extraction", run_entity_extraction)
    graph.add_node("entity_linking", run_entity_linking)
    graph.add_node("relation_extraction", run_relation_extraction)
    graph.add_node("attribute_extraction", run_attribute_extraction)
    graph.add_node("schema_mapping", run_schema_mapping)
    graph.add_node("ontology_construction", run_ontology_construction)
    graph.add_node("reasoning", run_reasoning)
    graph.add_node("validation", run_validation)

    graph.set_entry_point("input_ingestion")

    graph.add_edge("input_ingestion", "text_normalization")
    graph.add_edge("text_normalization", "coreference_resolution")
    graph.add_edge("coreference_resolution", "entity_extraction")
    graph.add_edge("entity_extraction", "entity_linking")
    graph.add_edge("entity_linking", "relation_extraction")
    graph.add_edge("relation_extraction", "attribute_extraction")
    graph.add_edge("attribute_extraction", "schema_mapping")
    graph.add_edge("schema_mapping", "ontology_construction")
    graph.add_edge("ontology_construction", "reasoning")
    graph.add_edge("reasoning", "validation")

    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "coreference_resolution": "coreference_resolution",
            "entity_extraction": "entity_extraction",
            "relation_extraction": "relation_extraction",
            "end": END,
        },
    )

    return graph.compile()


def run_pipeline(raw_text: str, metadata: Dict[str, str] | None = None) -> PipelineState:
    app = build_graph()
    initial_state: PipelineState = {
        "document": Document(raw_text=raw_text, metadata=metadata or {}),
        "iteration": 0,
    }
    result = app.invoke(initial_state)
    return result


if __name__ == "__main__":
    sample = "Tom Cruise starred in Top Gun. He became a global icon in 1986."
    output = run_pipeline(sample, {"source": "demo", "date": "2026-03-20", "domain": "film"})
    print("Validation errors:", output.get("validation_errors", []))
    print("Triples:", len(output.get("validated_ontology", {}).get("triples", [])))
