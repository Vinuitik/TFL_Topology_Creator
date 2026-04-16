from __future__ import annotations

"""Rewrite raw input into Wikipedia-style encyclopedic prose via LLM.

This runs immediately after input_ingestion and before text_normalization.
It handles both unstructured text (legal/regulatory prose) and structured
data (JSON, key-value dumps) by paraphrasing them into clean declarative
sentences that REBEL and downstream LLM states can process reliably.
"""

import logging

from schemas import Document, PipelineState
from service.llm import call_llm

log = logging.getLogger(__name__)


def run_preprocessing(state: PipelineState) -> PipelineState:
    document = state.get("document")
    if document is None:
        return {}

    raw = (document.raw_text or "").strip()
    if not raw:
        return {}

    try:
        result = call_llm("preprocessing", raw)
        paraphrased = result.get("paraphrased_text", "").strip()
        if not paraphrased:
            raise ValueError("Empty paraphrased_text in LLM response")
    except Exception as exc:
        log.warning("Preprocessing LLM call failed, passing raw text through: %s", exc)
        return {}

    # Replace document with paraphrased version; metadata is preserved.
    return {
        "document": Document(
            raw_text=paraphrased,
            metadata=document.metadata,
        )
    }
