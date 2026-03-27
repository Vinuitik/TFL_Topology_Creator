from __future__ import annotations

"""Run REBEL to extract (subject, predicate, object) triplets from resolved text."""

import logging
import re
from typing import List

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from schemas import PipelineState, Triplet

log = logging.getLogger(__name__)

_MODEL_NAME = "Babelscape/rebel-large"
_tokenizer = None
_model = None


def _load_model() -> None:
    global _tokenizer, _model
    if _tokenizer is None:
        log.info("Loading REBEL model %s", _MODEL_NAME)
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        _model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME)
        log.info("REBEL model loaded")


def _parse_rebel_output(text: str) -> List[dict]:
    """Parse REBEL linearized output into raw triplet dicts.

    REBEL format: <triplet> subject <subj> object <obj> predicate
    """
    triplets = []
    current: dict | None = None
    part = "subject"

    for token in text.split():
        if token == "<triplet>":
            if current and all(current[k] for k in ("subject", "predicate", "object")):
                triplets.append(current)
            current = {"subject": "", "predicate": "", "object": ""}
            part = "subject"
        elif token == "<subj>":
            part = "object"
        elif token == "<obj>":
            part = "predicate"
        elif current is not None:
            current[part] = (current[part] + " " + token).strip()

    if current and all(current[k] for k in ("subject", "predicate", "object")):
        triplets.append(current)

    return triplets


def _extract_from_sentence(sentence: str) -> List[Triplet]:
    log.debug("Processing sentence: %r", sentence)

    inputs = _tokenizer(
        sentence,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    )
    outputs = _model.generate(
        **inputs,
        max_length=512,
        num_beams=4,
        early_stopping=True,
    )
    decoded = _tokenizer.decode(outputs[0], skip_special_tokens=False)
    log.debug("REBEL raw output: %r", decoded)

    triplets = [
        Triplet(
            subject=t["subject"],
            predicate=t["predicate"],
            object=t["object"],
            provenance_sentence=sentence,
        )
        for t in _parse_rebel_output(decoded)
    ]
    log.debug("Parsed %d triplet(s): %s", len(triplets), [(t.subject, t.predicate, t.object) for t in triplets])
    return triplets


def run_extraction(state: PipelineState) -> PipelineState:
    resolved = state.get("resolved_document")
    if resolved is None:
        log.warning("run_extraction called with no resolved_document in state")
        return state

    _load_model()

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", resolved.text) if s.strip()]
    log.info("Extracting from %d sentence(s)", len(sentences))

    triplets: List[Triplet] = []
    for sentence in sentences:
        triplets.extend(_extract_from_sentence(sentence))

    log.info("Extraction complete — %d triplet(s) total", len(triplets))

    state["triplets"] = triplets
    state["low_confidence"] = len(triplets) == 0
    return state
