from __future__ import annotations

"""Ensure the pipeline starts with a Document and iteration counter."""

from schemas import Document, PipelineState


def run_input_ingestion(state: PipelineState) -> PipelineState:
    if "document" in state:
        return {}

    return {
        "document": Document(raw_text="", metadata={}),
        "iteration": 0,
    }
