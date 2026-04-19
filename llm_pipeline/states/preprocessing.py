from __future__ import annotations

"""Rewrite raw input into Wikipedia-style encyclopedic prose via LLM.

This runs immediately after input_ingestion and before text_normalization.
It handles both unstructured text (legal/regulatory prose) and structured
data (JSON, key-value dumps) by paraphrasing them into clean declarative
sentences that REBEL and downstream LLM states can process reliably.

Large inputs are split into sentence-bounded chunks and processed
sequentially; outputs are concatenated into a single document.
"""

import logging

from schemas import Document, PipelineState
from service.llm import call_llm
from states.chunk_utils import CHUNK_MAX_WORDS, make_chunks, split_sentences

log = logging.getLogger(__name__)


def _paraphrase_chunk(chunk_text: str) -> str | None:
    try:
        result = call_llm("preprocessing", chunk_text)
        paraphrased = result.get("paraphrased_text", "").strip()
        return paraphrased or None
    except Exception as exc:
        log.warning("Preprocessing LLM call failed for chunk: %s", exc)
        return None


def run_preprocessing(state: PipelineState) -> PipelineState:
    document = state.get("document")
    if document is None:
        return {}

    raw = (document.raw_text or "").strip()
    if not raw:
        return {}

    word_count = len(raw.split())

    if word_count <= CHUNK_MAX_WORDS:
        result = _paraphrase_chunk(raw)
        paraphrased = result or ""
    else:
        sentences = split_sentences(raw)
        chunks = make_chunks(sentences, CHUNK_MAX_WORDS)
        log.info("Preprocessing: %d words → %d chunks", word_count, len(chunks))
        parts: list[str] = []
        for i, chunk_sents in enumerate(chunks):
            chunk_text = " ".join(chunk_sents)
            part = _paraphrase_chunk(chunk_text)
            if part:
                parts.append(part)
            else:
                log.warning("Preprocessing chunk %d/%d failed, using raw chunk", i + 1, len(chunks))
                parts.append(chunk_text)
        paraphrased = " ".join(parts)

    if not paraphrased:
        log.warning("Preprocessing produced empty output, passing raw text through")
        return {}

    return {
        "document": Document(
            raw_text=paraphrased,
            metadata=document.metadata,
        )
    }
