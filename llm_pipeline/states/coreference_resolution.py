from __future__ import annotations

"""Resolve coreferences using spacy-experimental en_coreference_web_trf.

The model outputs span groups keyed "coref_clusters_N" in doc.spans.
Each group is one coreference cluster (all mentions of the same entity).
Canonical mention = longest span by character count (tends to be the full
proper name; pronouns and short aliases are naturally shorter).
Replacements are applied right-to-left so earlier offsets stay valid.
"""

import logging
from typing import Any

from schemas import PipelineState, ResolvedDocument

log = logging.getLogger(__name__)

_nlp: Any = None


def _get_nlp() -> Any:
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_coreference_web_trf")
        log.info("spacy-experimental coreference model loaded")
    return _nlp


def _resolve(text: str) -> str:
    nlp = _get_nlp()
    doc = nlp(text)

    replacements: list[tuple[int, int, str]] = []

    for key, spans in doc.spans.items():
        if not key.startswith("coref_clusters"):
            continue
        if not spans:
            continue

        canonical = max(spans, key=lambda s: len(s.text)).text

        for span in spans:
            if span.text == canonical:
                continue
            replacements.append((span.start_char, span.end_char, canonical))

    if not replacements:
        return text

    # Right-to-left so earlier char offsets stay valid
    replacements.sort(key=lambda x: x[0], reverse=True)
    chars = list(text)
    for start, end, repl in replacements:
        chars[start:end] = list(repl)

    return "".join(chars)


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
