from __future__ import annotations

"""Resolve coreferences (pronouns, aliases) via LLM with naive fallback."""

import logging
import re

from schemas import PipelineState, ResolvedDocument
from service.llm import call_llm

log = logging.getLogger(__name__)


def _llm_resolve(text: str) -> str | None:
    try:
        result = call_llm("coreference_resolution", text)
        resolved = result.get("resolved_text", "")
        return resolved if resolved else None
    except Exception as exc:
        log.warning("LLM coreference failed, using fallback: %s", exc)
        return None


# --- naive fallback (original prototype, kept for reference) ---
# _PRONOUNS = {"he", "she", "it", "they", "him", "her", "them"}
#
# def _naive_resolve(text: str) -> tuple[str, dict, list]:
#     tokens = re.findall(r"\b\w+\b", text)
#     candidates = [t for t in tokens if t and t[0].isupper()]
#     canonical = candidates[0] if candidates else "UnknownEntity"
#     mapping = {}
#     preserved_spans = []
#     resolved_text = text
#     for match in re.finditer(r"\b\w+\b", text):
#         word = match.group(0)
#         if word.lower() in _PRONOUNS:
#             mapping[word] = canonical
#             preserved_spans.append((match.start(), match.end(), word))
#     for pronoun, target in mapping.items():
#         resolved_text = re.sub(rf"\b{re.escape(pronoun)}\b", target, resolved_text)
#     return resolved_text, mapping, preserved_spans


def run_coreference_resolution(state: PipelineState) -> PipelineState:
    normalized = state.get("normalized_document")
    if normalized is None:
        return {}

    text = normalized.text
    resolved_text = _llm_resolve(text)

    if resolved_text is None:
        # Fallback: pass text through unchanged rather than corrupt it with naive replacement
        log.warning("Coreference resolution skipped — LLM unavailable, using raw text")
        resolved_text = text

    return {
        "resolved_document": ResolvedDocument(
            text=resolved_text,
            coref_mapping={},
            preserved_spans=[],
        )
    }
