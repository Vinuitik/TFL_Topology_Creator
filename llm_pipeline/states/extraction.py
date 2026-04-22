from __future__ import annotations

"""Run REBEL + spaCy NER to extract (subject, predicate, object) triplets from resolved text."""

import logging
import re
from typing import List, Optional

import spacy
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from schemas import PipelineState, Triplet

log = logging.getLogger(__name__)

_MODEL_NAME = "Babelscape/rebel-large"
_tokenizer = None
_model = None
_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_SPACY_MODEL = "en_core_web_lg"
_nlp: Optional[spacy.language.Language] = None

# spaCy entity types to include; mapped to a transport-domain class name
_SPACY_TYPE_MAP = {
    "ORG": "Organization",
    "GPE": "Place",
    "LOC": "Place",
    "FAC": "Facility",
    "LAW": "Regulation",
    "PRODUCT": "TransportProduct",
    "EVENT": "TransportEvent",
}

# Minimum token length — filters out short noisy spans
_MIN_ENTITY_CHARS = 3


def _load_spacy() -> spacy.language.Language:
    global _nlp
    if _nlp is None:
        log.info("Loading spaCy model %s (CPU)", _SPACY_MODEL)
        _nlp = spacy.load(_SPACY_MODEL, exclude=["parser", "senter"])
        log.info("spaCy model loaded")
    return _nlp


def _extract_spacy_triplets(text: str, provenance: str) -> List[Triplet]:
    """Run spaCy NER and emit (entity, type, ClassName) triplets for relevant spans."""
    nlp = _load_spacy()
    doc = nlp(text)
    seen: set = set()
    triplets: List[Triplet] = []
    for ent in doc.ents:
        label = _SPACY_TYPE_MAP.get(ent.label_)
        if label is None:
            continue
        surface = ent.text.strip()
        if len(surface) < _MIN_ENTITY_CHARS or surface.lower() in seen:
            continue
        seen.add(surface.lower())
        triplets.append(Triplet(
            subject=surface,
            predicate="type",
            object=label,
            provenance_sentence=provenance,
        ))
        log.debug("spaCy NER: (%r, type, %r)", surface, label)
    log.info("spaCy NER: %d type-assertion triplets from %d chars", len(triplets), len(text))
    return triplets


def _load_model() -> None:
    global _tokenizer, _model
    if _tokenizer is None:
        log.info("Loading REBEL model %s on %s", _MODEL_NAME, _device)
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        _model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME).to(_device)
        log.info("REBEL model loaded on %s", _device)


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
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    outputs = _model.generate(
        **inputs,
        max_length=512,
        num_beams=4,
        early_stopping=True,
    )
    decoded = _tokenizer.decode(outputs[0], skip_special_tokens=False)
    decoded = decoded.replace("<s>", "").replace("</s>", "")
    print(f"\n[REBEL raw] {decoded!r}")

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


def _unload_model() -> None:
    global _tokenizer, _model
    _tokenizer = None
    _model = None
    torch.cuda.empty_cache()
    log.info("REBEL model unloaded, VRAM released")


def run_extraction(state: PipelineState) -> PipelineState:
    resolved = state.get("resolved_document")
    if resolved is None:
        log.warning("run_extraction called with no resolved_document in state")
        return state

    full_text = resolved.text
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()]
    log.info("Extracting from %d sentence(s)", len(sentences))

    # REBEL: relation triplets (runs on GPU)
    _load_model()
    rebel_triplets: List[Triplet] = []
    for sentence in sentences:
        rebel_triplets.extend(_extract_from_sentence(sentence))
    log.info("REBEL: %d triplet(s)", len(rebel_triplets))
    # _unload_model() — PERSIST in VRAM for speed if processing batch

    # spaCy NER: type-assertion triplets (runs on CPU, no VRAM)
    spacy_triplets = _extract_spacy_triplets(full_text, provenance=full_text[:200])

    # Merge: REBEL triplets first, then spaCy type assertions
    # Filter out empty/whitespace-only subjects or objects before merging
    all_triplets: List[Triplet] = []
    for t in rebel_triplets + spacy_triplets:
        if t.subject.strip() and t.object.strip() and len(t.subject.strip()) >= 2:
            all_triplets.append(t)

    log.info("Extraction complete — %d rebel + %d spacy = %d total triplet(s)",
             len(rebel_triplets), len(spacy_triplets), len(all_triplets))

    state["triplets"] = all_triplets
    state["low_confidence"] = len(all_triplets) == 0
    return state
