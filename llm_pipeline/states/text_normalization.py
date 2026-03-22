from __future__ import annotations

"""Clean text and produce sentence/token views for downstream states."""

import re

from schemas import NormalizedDocument, PipelineState


def run_text_normalization(state: PipelineState) -> PipelineState:
    document = state.get("document")
    if document is None:
        return {}

    cleaned = re.sub(r"\s+", " ", document.raw_text or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    tokens = re.findall(r"\b\w+\b", cleaned)

    return {
        "normalized_document": NormalizedDocument(
            text=cleaned,
            sentences=sentences,
            tokens=tokens,
        )
    }
