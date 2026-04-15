from __future__ import annotations

from pydantic import BaseModel


class Triplet(BaseModel):
    subject: str
    predicate: str
    object: str
    # confidence: float = 0.0  # REBEL never sets this; always 0.0 — commented until extraction provides real scores
    provenance_sentence: str = ""
