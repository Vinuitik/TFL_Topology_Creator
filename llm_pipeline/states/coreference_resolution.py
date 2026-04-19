from __future__ import annotations

import logging
import os
from typing import Any

import grpc

import coref_pb2
import coref_pb2_grpc
from schemas import PipelineState, ResolvedDocument

log = logging.getLogger(__name__)

_COREF_HOST = os.getenv("COREF_SERVICE_HOST", "coref-service:50051")

_channel: Any = None
_stub: Any = None


def _get_stub() -> coref_pb2_grpc.CoreferenceServiceStub:
    global _channel, _stub
    if _stub is None:
        _channel = grpc.insecure_channel(_COREF_HOST)
        _stub = coref_pb2_grpc.CoreferenceServiceStub(_channel)
    return _stub


def _resolve(text: str) -> str:
    stub = _get_stub()
    response = stub.Resolve(coref_pb2.ResolveRequest(text=text))
    return response.resolved_text


def run_coreference_resolution(state: PipelineState) -> PipelineState:
    normalized = state.get("normalized_document")
    if normalized is None:
        return {}

    text = normalized.text
    try:
        resolved_text = _resolve(text)
        log.info("Coreference resolution complete (chars: %d → %d)", len(text), len(resolved_text))
    except Exception as exc:
        log.warning("Coreference resolution failed, using raw text: %s", exc)
        resolved_text = text

    return {
        "resolved_document": ResolvedDocument(
            text=resolved_text,
            coref_mapping={},
            preserved_spans=[],
        )
    }
