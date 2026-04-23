"""Unit tests for pure (no-network, no-model) pipeline states."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from schemas.document import NormalizedDocument, ResolvedDocument
from schemas.entities import Triplet
from states.extraction import _parse_rebel_output
from states.coreference_resolution import run_coreference_resolution
from states.schema_mapping import run_schema_mapping
from states.validation import run_validation
from states.feedback_router import route_after_validation


# ── _parse_rebel_output ────────────────────────────────────────────────────

def test_parse_single():
    raw = "<triplet> TfL <subj> London Underground <obj> operator"
    assert _parse_rebel_output(raw) == [
        {"subject": "TfL", "predicate": "operator", "object": "London Underground"}
    ]

def test_parse_multiple():
    raw = (
        "<triplet> TfL <subj> Oyster card <obj> fare payment method"
        " <triplet> Oyster card <subj> all TfL services <obj> valid for"
    )
    result = _parse_rebel_output(raw)
    assert len(result) == 2
    assert result[0]["subject"] == "TfL"
    assert result[1]["predicate"] == "valid for"

def test_parse_incomplete_skipped():
    assert _parse_rebel_output("<triplet> Piccadilly line <subj> Heathrow Airport") == []

def test_parse_empty():
    assert _parse_rebel_output("") == []

def test_parse_no_tokens():
    assert _parse_rebel_output("plain text without special tokens") == []


# ── run_coreference_resolution ─────────────────────────────────────────────

def _coref_state(text: str) -> dict:
    return {"normalized_document": NormalizedDocument(text=text), "iteration": 0}

def test_coref_replaces_pronoun():
    state = run_coreference_resolution(_coref_state("TfL suspended it. It was expected."))
    assert "TfL" in state["resolved_document"].text
    assert state["resolved_document"].coref_mapping != {} or "it" not in state["resolved_document"].text.lower().split()

def test_coref_no_pronouns():
    state = run_coreference_resolution(_coref_state("TfL operates buses."))
    assert state["resolved_document"].text == "TfL operates buses."

def test_coref_missing_normalized_document():
    assert run_coreference_resolution({"iteration": 0}) == {}


# ── run_schema_mapping ─────────────────────────────────────────────────────

def _triplet(s, p, o):
    return Triplet(subject=s, predicate=p, object=o, confidence=1.0, provenance_sentence="test")

def test_schema_mapping_produces_nodes_and_edges():
    triplets = [_triplet("TfL", "operates", "Central line")]
    result = run_schema_mapping({"triplets": triplets, "iteration": 0})
    mg = result["mapped_graph"]
    assert len(mg["nodes"]) == 2
    assert len(mg["edges"]) == 1

def test_schema_mapping_empty_triplets():
    result = run_schema_mapping({"triplets": [], "iteration": 0})
    assert result["mapped_graph"]["nodes"] == []
    assert result["mapped_graph"]["edges"] == []

def test_schema_mapping_numeric_literal():
    triplets = [_triplet("Route 73", "stops", "42")]
    result = run_schema_mapping({"triplets": triplets, "iteration": 0})
    edge = result["mapped_graph"]["edges"][0]
    assert "object_literal" in edge
    assert edge["object_datatype"].endswith("integer")

def test_schema_mapping_known_predicate_matched():
    triplets = [_triplet("TfL", "operates", "Piccadilly line")]
    result = run_schema_mapping({"triplets": triplets, "iteration": 0})
    edge = result["mapped_graph"]["edges"][0]
    assert "example.org" in edge["predicate_iri"]


# ── run_validation ─────────────────────────────────────────────────────────

_BASE = "http://example.org/pt#"

def _valid_triple(s_slug, p_slug, o_slug):
    return {
        "subject": f"{_BASE}{s_slug}",
        "predicate": f"{_BASE}{p_slug}",
        "object": f"{_BASE}{o_slug}",
        "is_literal": False,
    }

def test_validation_passes_clean_ontology():
    state = {
        "inferred_ontology": {"triples": [_valid_triple("TfL", "operates", "CentralLine")]},
        "unmapped_predicates": [],
        "linking_conflicts": 0,
        "iteration": 0,
    }
    result = run_validation(state)
    assert result["failed_validation"] is False
    assert result["validation_errors"] == []

def test_validation_fails_empty_ontology():
    state = {"inferred_ontology": {"triples": []}, "unmapped_predicates": [], "linking_conflicts": 0, "iteration": 0}
    result = run_validation(state)
    assert result["failed_validation"] is True

def test_validation_fails_bad_iris():
    state = {
        "inferred_ontology": {"triples": [{"subject": "TfL", "predicate": "operates", "object": "CentralLine", "is_literal": False}]},
        "unmapped_predicates": [],
        "linking_conflicts": 0,
        "iteration": 0,
    }
    result = run_validation(state)
    assert result["failed_validation"] is True

def test_validation_reports_linking_conflicts():
    state = {
        "inferred_ontology": {"triples": [_valid_triple("A", "operates", "B")]},
        "unmapped_predicates": [],
        "linking_conflicts": 3,
        "iteration": 0,
    }
    result = run_validation(state)
    assert result["failed_validation"] is True
    assert any("conflict" in e.lower() for e in result["validation_errors"])


# ── route_after_validation ─────────────────────────────────────────────────

def test_router_ends_when_max_iterations():
    assert route_after_validation({"iteration": 2, "failed_validation": True, "reroute_target": "extraction"}) == "end"

def test_router_follows_reroute_target():
    assert route_after_validation({"iteration": 0, "failed_validation": True, "reroute_target": "schema_mapping"}) == "schema_mapping"

def test_router_ends_on_success():
    assert route_after_validation({"iteration": 0, "failed_validation": False, "reroute_target": "end"}) == "end"

def test_router_defaults_to_entity_linking_on_failure():
    assert route_after_validation({"iteration": 0, "failed_validation": True}) == "entity_linking"
