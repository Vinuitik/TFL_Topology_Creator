"""Shared utilities for the LLM pipeline."""
from __future__ import annotations

import re
from typing import Optional

# ── literal detection ────────────────────────────────────────────────────────

_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
)

_DATE_PATTERNS = [
    re.compile(rf'\b\d{{1,2}}\s+{_MONTHS}\s+\d{{4}}\b', re.IGNORECASE),   # "8 August 1898"
    re.compile(rf'\b{_MONTHS}\s+\d{{1,2}},?\s+\d{{4}}\b', re.IGNORECASE), # "August 8, 1898"
    re.compile(rf'\b{_MONTHS}\s+\d{{4}}\b', re.IGNORECASE),                # "February 1904"
    re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'),                            # "1/8/1898"
    re.compile(r'\b(?:early|mid|late)[-\s]\d{4}s?\b', re.IGNORECASE),      # "early 1900s"
    re.compile(r'\b\d{4}s\b'),                                              # "1900s"
]


def is_literal(value: str) -> bool:
    """Return True if value should be treated as a datatype literal, not an OWL entity."""
    cleaned = value.strip()
    if not cleaned:
        return False
    # integers and decimals
    if re.fullmatch(r'-?\d+', cleaned) or re.fullmatch(r'-?\d+\.\d+', cleaned):
        return True
    # date strings
    for pattern in _DATE_PATTERNS:
        if pattern.search(cleaned):
            return True
    return False


def literal_datatype(value: str) -> str:
    """Return an XSD datatype string for a detected literal value."""
    cleaned = value.strip()
    if re.fullmatch(r'-?\d+', cleaned):
        return 'xsd:integer'
    if re.fullmatch(r'-?\d+\.\d+', cleaned):
        return 'xsd:decimal'
    for pattern in _DATE_PATTERNS:
        if pattern.search(cleaned):
            return 'xsd:string'
    return 'xsd:string'


# ── KNN context for classification ───────────────────────────────────────────

def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def find_knn_by_embedding(
    name: str,
    name_emb: list[float],
    labeled: dict[str, str],
    embeddings: dict[str, list[float]],
    k: int = 3,
) -> list[str]:
    """Return top-k semantically nearest labeled entities as prompt context strings.

    labeled:    {entity_name: kind}
    embeddings: {entity_name: vector}
    Returns:    ['"District" → class', '"Sutton" → individual', ...]
    """
    if not name_emb or not labeled:
        return []

    scored: list[tuple[float, str, str]] = []
    for label_name, kind in labeled.items():
        if label_name == name:
            continue
        emb = embeddings.get(label_name)
        if not emb:
            continue
        scored.append((cosine(name_emb, emb), label_name, kind))

    scored.sort(reverse=True)
    return [f'"{n}" → {k}' for _, n, k in scored[:k]]
