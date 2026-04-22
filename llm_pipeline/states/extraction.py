from __future__ import annotations

"""Run REBEL + spaCy NER + LLM to extract (subject, predicate, object) triplets from resolved text."""

import gc
import logging
import re
from typing import List, Optional

import spacy
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from schemas import PipelineState, Triplet
from service.llm import call_llm

log = logging.getLogger(__name__)

_MODEL_NAME = "Babelscape/rebel-large"
_tokenizer = None
_model = None
_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_SPACY_MODEL = "en_core_web_lg"
_nlp: Optional[spacy.language.Language] = None

_LLM_CHUNK_WORDS = 350  # words per chunk sent to LLM
_ENTITY_MODEL = __import__("os").getenv("OLLAMA_ENTITY_MODEL")
_EMBED_MODEL = __import__("os").getenv("OLLAMA_EMBED_MODEL")
_OLLAMA_URL = __import__("os").getenv("OLLAMA_URL")

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

_MIN_ENTITY_CHARS = 3


# ── VRAM management ─────────────────────────────────────────────────────────

def _evict_model(model_name: str) -> None:
    """Ask Ollama to unload a model from VRAM immediately (keep_alive=0).
    The model reloads automatically on next use."""
    try:
        import requests as _requests
        _log_memory(f"pre-evict-{model_name}")
        _requests.post(
            _OLLAMA_URL,
            json={"model": model_name, "keep_alive": 0},
            timeout=15,
        )
        log.info("VRAM eviction requested for model '%s'", model_name)
        _log_memory(f"post-evict-{model_name}")
    except Exception as exc:
        log.warning("Failed to evict model '%s' from VRAM: %s", model_name, exc)


# ── memory diagnostics ──────────────────────────────────────────────────────

def _log_memory(label: str) -> None:
    try:
        import os, psutil
        rss_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2
        log.info("MEM [%s] process_rss=%.0fMB", label, rss_mb)
    except Exception:
        pass
    if torch.cuda.is_available():
        alloc = torch.cuda.memory_allocated() / 1024 ** 2
        reserved = torch.cuda.memory_reserved() / 1024 ** 2
        log.info("VRAM [%s] allocated=%.0fMB reserved=%.0fMB", label, alloc, reserved)


# ── spaCy NER ───────────────────────────────────────────────────────────────

def _load_spacy() -> spacy.language.Language:
    global _nlp
    if _nlp is None:
        log.info("Loading spaCy model %s (CPU)", _SPACY_MODEL)
        _log_memory("pre-spacy-load")
        _nlp = spacy.load(_SPACY_MODEL, exclude=["parser", "senter"])
        _log_memory("post-spacy-load")
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


# ── REBEL ───────────────────────────────────────────────────────────────────

def _load_model() -> None:
    global _tokenizer, _model
    if _tokenizer is None:
        log.info("Loading REBEL model %s on %s", _MODEL_NAME, _device)
        _log_memory("pre-rebel-load")
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        _model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME).to(_device)
        _log_memory("post-rebel-load")
        log.info("REBEL model loaded on %s", _device)


def _parse_rebel_output(text: str) -> List[dict]:
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
    log.debug("[REBEL raw] %r", decoded)

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
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    _log_memory("post-rebel-unload")
    log.info("REBEL model unloaded, VRAM released")


def _unload_spacy() -> None:
    global _nlp
    _nlp = None
    gc.collect()
    _log_memory("post-spacy-unload")
    log.info("spaCy model unloaded")


# ── LLM extraction ──────────────────────────────────────────────────────────

def _chunk_text(text: str, max_words: int) -> List[str]:
    """Split text into chunks of at most max_words words, breaking on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    current_words: List[str] = []
    for sentence in sentences:
        words = sentence.split()
        if current_words and len(current_words) + len(words) > max_words:
            chunks.append(" ".join(current_words))
            current_words = words
        else:
            current_words.extend(words)
    if current_words:
        chunks.append(" ".join(current_words))
    return chunks


def _extract_llm_triplets(text: str) -> List[Triplet]:
    """Send text chunks to LLM and collect extracted triplets."""
    chunks = _chunk_text(text, _LLM_CHUNK_WORDS)
    log.info("LLM extraction: %d chunk(s) from %d chars", len(chunks), len(text))

    triplets: List[Triplet] = []
    for idx, chunk in enumerate(chunks):
        try:
            result = call_llm(
                "extraction",
                f"\n{chunk}\n",
                model=_ENTITY_MODEL,
                extra_options={"num_predict": 1024, "repeat_penalty": 1.2},
            )
            raw_triplets = result.get("triplets", [])
            log.info("LLM extraction chunk %d/%d: %d triplet(s)", idx + 1, len(chunks), len(raw_triplets))
            for rt in raw_triplets:
                subj = str(rt.get("subject", "")).strip()
                pred = str(rt.get("predicate", "")).strip()
                obj = str(rt.get("object", "")).strip()
                if subj and pred and obj and len(subj) >= 2:
                    triplets.append(Triplet(
                        subject=subj,
                        predicate=pred,
                        object=obj,
                        provenance_sentence=chunk[:200],
                    ))
        except Exception as exc:
            log.warning("LLM extraction chunk %d/%d failed: %s", idx + 1, len(chunks), exc)

    log.info("LLM extraction: %d total triplet(s)", len(triplets))
    return triplets


# ── state ───────────────────────────────────────────────────────────────────

def run_extraction(state: PipelineState) -> PipelineState:
    resolved = state.get("resolved_document")
    if resolved is None:
        log.warning("run_extraction called with no resolved_document in state")
        return state

    full_text = resolved.text
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if s.strip()]
    log.info("Extracting from %d sentence(s)", len(sentences))
    _log_memory("extraction-start")

    # ── 1. REBEL: relation triplets (GPU) ───────────────────────────────────
    # Evict all Ollama models first — they share the same GPU and will cause
    # cudaErrorUnknown (silent OOM) during beam search if left resident.
    if _ENTITY_MODEL:
        _evict_model(_ENTITY_MODEL)
    if _EMBED_MODEL:
        _evict_model(_EMBED_MODEL)
    _load_model()
    rebel_triplets: List[Triplet] = []
    for sentence in sentences:
        try:
            rebel_triplets.extend(_extract_from_sentence(sentence))
        except Exception as exc:
            log.error("REBEL failed on sentence (skipping): %s | sentence=%.80r", exc, sentence)
    log.info("REBEL: %d triplet(s)", len(rebel_triplets))
    _unload_model()  # free VRAM before CPU-heavy stages

    # ── 2. spaCy NER: type-assertion triplets (CPU) ─────────────────────────
    try:
        spacy_triplets = _extract_spacy_triplets(full_text, provenance=full_text[:200])
    except Exception as exc:
        log.error("spaCy extraction failed: %s", exc, exc_info=True)
        _log_memory("spacy-failure")
        spacy_triplets = []
    finally:
        _unload_spacy()

    # ── 3. LLM extraction: relation triplets (Ollama HTTP) ──────────────────
    # Evict the embedding model before LLM extraction — it is not needed until
    # entity_linking and would otherwise compete for VRAM with the entity model.
    if _EMBED_MODEL:
        _evict_model(_EMBED_MODEL)
    _log_memory("pre-llm-extraction")
    try:
        llm_triplets = _extract_llm_triplets(full_text)
    except Exception as exc:
        log.error("LLM extraction failed: %s", exc, exc_info=True)
        llm_triplets = []

    # ── Merge all sources ────────────────────────────────────────────────────
    all_triplets: List[Triplet] = []
    seen_keys: set = set()
    for t in rebel_triplets + spacy_triplets + llm_triplets:
        if not (t.subject.strip() and t.object.strip() and len(t.subject.strip()) >= 2):
            continue
        key = (t.subject.lower(), t.predicate.lower(), t.object.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        all_triplets.append(t)

    log.info(
        "Extraction complete — %d rebel + %d spacy + %d llm = %d total (after dedup)",
        len(rebel_triplets), len(spacy_triplets), len(llm_triplets), len(all_triplets),
    )
    _log_memory("extraction-end")

    state["triplets"] = all_triplets
    state["low_confidence"] = len(all_triplets) == 0
    return state
