from __future__ import annotations

"""Replace pronouns with canonical entities while preserving original spans."""

import re

from schemas import PipelineState, ResolvedDocument


_PRONOUNS = {"he", "she", "it", "they", "him", "her", "them"}


def run_coreference_resolution(state: PipelineState) -> PipelineState:
    normalized = state.get("normalized_document")
    if normalized is None:
        return {}

    text = normalized.text
    tokens = re.findall(r"\b\w+\b", text)
    candidates = [t for t in tokens if t and t[0].isupper()]
    canonical = candidates[0] if candidates else "UnknownEntity"

    mapping = {}
    preserved_spans = []
    resolved_text = text

    for match in re.finditer(r"\b\w+\b", text):
        word = match.group(0)
        if word.lower() in _PRONOUNS:
            mapping[word] = canonical
            preserved_spans.append((match.start(), match.end(), word))

    for pronoun, target in mapping.items():
        resolved_text = re.sub(rf"\b{re.escape(pronoun)}\b", target, resolved_text)

    return {
        "resolved_document": ResolvedDocument(
            text=resolved_text,
            coref_mapping=mapping,
            preserved_spans=preserved_spans,
        )
    }
