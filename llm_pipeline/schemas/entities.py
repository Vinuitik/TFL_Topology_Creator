from __future__ import annotations

from pydantic import BaseModel


class Triplet(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = 0.0
    provenance_sentence: str = ""
