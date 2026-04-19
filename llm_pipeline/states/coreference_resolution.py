from __future__ import annotations

"""Resolve coreferences (pronouns, aliases) via LLM with naive fallback.

Large inputs are split into sentence-bounded chunks. Each chunk is resolved
independently; the previous OVERLAP_SENTENCES sentences are prepended as
read-only context so cross-boundary pronoun resolution still works.
"""

import logging
from typing import List

from schemas import PipelineState, ResolvedDocument
from service.llm import call_llm
from states.chunk_utils import CHUNK_MAX_WORDS, OVERLAP_SENTENCES, make_chunks, split_sentences

log = logging.getLogger(__name__)


def _llm_resolve_chunk(chunk_text: str, context_sentences: List[str]) -> str | None:
    if context_sentences:
        context_str = " ".join(context_sentences)
        params = (
            f"\n[CONTEXT — do not resolve, reference only]:\n{context_str}"
            f"\n\n[RESOLVE coreferences in this part only]:\n{chunk_text}"
        )
    else:
        params = f"\n[RESOLVE coreferences in this part only]:\n{chunk_text}"

    try:
        result = call_llm("coreference_resolution", params)
        resolved = result.get("resolved_text", "")
        return resolved if resolved else None
    except Exception as exc:
        log.warning("LLM coreference failed for chunk: %s", exc)
        return None


def run_coreference_resolution(state: PipelineState) -> PipelineState:
    normalized = state.get("normalized_document")
    if normalized is None:
        return {}

    text = normalized.text
    word_count = len(text.split())

    if word_count <= CHUNK_MAX_WORDS:
        resolved_text = _llm_resolve_chunk(text, [])
    else:
        sentences = split_sentences(text)
        chunks = make_chunks(sentences, CHUNK_MAX_WORDS)
        log.info("Coreference: %d words → %d chunks", word_count, len(chunks))

        parts: list[str] = []
        for i, chunk_sents in enumerate(chunks):
            chunk_text = " ".join(chunk_sents)
            context = chunks[i - 1][-OVERLAP_SENTENCES:] if i > 0 else []
            resolved = _llm_resolve_chunk(chunk_text, context)
            if resolved:
                parts.append(resolved)
            else:
                log.warning("Coreference chunk %d/%d failed, using raw chunk", i + 1, len(chunks))
                parts.append(chunk_text)

        resolved_text = " ".join(parts) if parts else None

    if resolved_text is None:
        log.warning("Coreference resolution skipped — LLM unavailable, using raw text")
        resolved_text = text

    return {
        "resolved_document": ResolvedDocument(
            text=resolved_text,
            coref_mapping={},
            preserved_spans=[],
        )
    }
