from __future__ import annotations

import logging

from schemas.document import ResolvedDocument
from states.extraction import _parse_rebel_output, run_extraction

logging.basicConfig(level=logging.DEBUG)


# ---------------------------------------------------------------------------
# _parse_rebel_output — pure unit tests
# ---------------------------------------------------------------------------


def test_parse_single_triplet():
    raw = "<triplet> TfL <subj> London Underground <obj> operator"
    result = _parse_rebel_output(raw)
    print(f"\n[parse] input:  {raw}")
    print(f"[parse] output: {result}")
    assert result == [{"subject": "TfL", "predicate": "operator", "object": "London Underground"}]


def test_parse_multiple_triplets():
    raw = (
        "<triplet> TfL <subj> Oyster card <obj> fare payment method"
        " <triplet> Oyster card <subj> all TfL services <obj> valid for"
    )
    result = _parse_rebel_output(raw)
    print(f"\n[parse] input:  {raw}")
    print(f"[parse] output: {result}")
    assert len(result) == 2
    assert result[0] == {"subject": "TfL", "predicate": "fare payment method", "object": "Oyster card"}
    assert result[1] == {"subject": "Oyster card", "predicate": "valid for", "object": "all TfL services"}


def test_parse_skips_incomplete_triplet():
    raw = "<triplet> Piccadilly line <subj> Heathrow Airport"
    result = _parse_rebel_output(raw)
    print(f"\n[parse] input:  {raw}")
    print(f"[parse] output: {result} (expected empty)")
    assert result == []


def test_parse_empty_string():
    assert _parse_rebel_output("") == []


def test_parse_no_special_tokens():
    assert _parse_rebel_output("TfL operates buses in London") == []


# ---------------------------------------------------------------------------
# run_extraction — real REBEL model (first test will be slow: model download)
# ---------------------------------------------------------------------------


def _state(text: str) -> dict:
    return {"resolved_document": ResolvedDocument(text=text), "iteration": 0}


def _print_triplets(label: str, triplets) -> None:
    print(f"\n[{label}] {len(triplets)} triplet(s):")
    for t in triplets:
        print(f"  ({t.subject!r}, {t.predicate!r}, {t.object!r})")


def _all_spans(triplets) -> set[str]:
    return {t.subject for t in triplets} | {t.object for t in triplets}


def test_tfl_service_suspension_notification():
    text = (
        "TfL suspended the Central line on 15 March 2026. "
        "TfL cited engineering works as the reason for the Central line suspension."
    )
    state = run_extraction(_state(text))
    _print_triplets("suspension", state["triplets"])
    spans = _all_spans(state["triplets"])

    assert len(state["triplets"]) > 0
    assert any("TfL" in s or "Central line" in s for s in spans)
    assert state["low_confidence"] is False


def test_tfl_oyster_card_terms():
    text = (
        "Passengers must validate an Oyster card before boarding. "
        "TfL issues penalty fares to passengers who do not validate an Oyster card."
    )
    state = run_extraction(_state(text))
    _print_triplets("oyster", state["triplets"])
    spans = _all_spans(state["triplets"])

    assert len(state["triplets"]) > 0
    assert any("Oyster card" in s or "TfL" in s for s in spans)


def test_tfl_piccadilly_line_route():
    text = (
        "The Piccadilly line connects Heathrow Airport to central London. "
        "TfL operates the Piccadilly line."
    )
    state = run_extraction(_state(text))
    _print_triplets("piccadilly", state["triplets"])
    spans = _all_spans(state["triplets"])

    assert len(state["triplets"]) > 0
    assert any("Piccadilly line" in s for s in spans)
    assert any("Heathrow Airport" in s or "London" in s for s in spans)


def test_tfl_bus_penalty_notice():
    text = (
        "TfL issued a penalty notice to a passenger on route 73. "
        "The passenger did not purchase a valid ticket before boarding route 73."
    )
    state = run_extraction(_state(text))
    _print_triplets("penalty", state["triplets"])

    assert len(state["triplets"]) > 0
    assert state["low_confidence"] is False


def test_provenance_sentence_attached():
    text = "TfL operates the Elizabeth line. The Elizabeth line serves Reading."
    state = run_extraction(_state(text))
    _print_triplets("provenance", state["triplets"])

    for t in state["triplets"]:
        print(f"  provenance: {t.provenance_sentence!r}")
        assert t.provenance_sentence != ""


def test_missing_resolved_document_returns_state_unchanged():
    state = {"iteration": 0}
    result = run_extraction(state)
    print(f"\n[missing_doc] returned state: {result}")
    assert result == {"iteration": 0}
