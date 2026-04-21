"""Integration smoke-test for the pipeline.

Run this ONLY when all services are up (Ollama, Redis, coref-service),
as it performs real model calls.  For pure offline unit tests see:
    llm_pipeline/tests/test_pipeline.py

Usage (from llm_pipeline/ directory):
    python test_pipeline.py
"""
from __future__ import annotations

import json
from agent import run_pipeline


def test_tfl_pipeline_integration() -> None:
    sample_text = (
        "The Northern line is a London Underground line operated by Transport for London. "
        "It runs from Edgware and High Barnet in the north to Morden and Battersea Power "
        "Station in the south, passing through 52 stations. "
        "Camden Town is an interchange station where the Edgware branch and the High Barnet "
        "branch both connect to the Charing Cross and Bank central sections. "
        "Passengers must hold a valid Oyster card or contactless payment when travelling. "
        "Under EU Regulation 1371/2007 passengers are entitled to compensation for delays "
        "of 60 minutes or more."
    )

    metadata = {
        "source": "integration_test",
        "domain": "public-transport",
        "sequence": "1",
    }

    print("Starting integration pipeline run …\n")
    state = run_pipeline(raw_text=sample_text, metadata=metadata)

    triplets = state.get("triplets", [])
    validated = state.get("validated_ontology", {})
    triples = validated.get("triples", [])
    errors = state.get("validation_errors", [])
    turtle = state.get("turtle_output", "")

    print(f"Triplets extracted  : {len(triplets)}")
    print(f"Validated triples   : {len(triples)}")
    print(f"Validation errors   : {errors}")
    print(f"Turtle output (chars): {len(turtle)}")

    # Spot-checks
    assert len(triplets) > 0, "REBEL produced no triplets"
    assert len(triples) > 0, "Ontology contains no triples after validation"
    assert not state.get("failed_validation", True), f"Validation failed: {errors}"
    # All subject/predicate IRIs must start with http://
    for t in triples:
        assert t["subject"].startswith("http"), f"Bad subject IRI: {t['subject']}"
        assert t["predicate"].startswith("http"), f"Bad predicate IRI: {t['predicate']}"
    # Namespace must be tfl, not pt
    assert "example.org/pt#" not in turtle, "Output still uses legacy pt# namespace"
    assert "example.org/tfl#" in turtle, "tfl# namespace not found in Turtle output"

    print("\n✓ Integration test passed.")
    print("\n--- Turtle (first 1500 chars) ---")
    print(turtle[:1500])


if __name__ == "__main__":
    test_tfl_pipeline_integration()