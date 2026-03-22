from __future__ import annotations

from typing import Dict, List, Tuple

from pydantic import BaseModel, Field


class Document(BaseModel):
    raw_text: str
    metadata: Dict[str, str] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    text: str
    sentences: List[str] = Field(default_factory=list)
    tokens: List[str] = Field(default_factory=list)


class ResolvedDocument(BaseModel):
    text: str
    coref_mapping: Dict[str, str] = Field(default_factory=dict)
    preserved_spans: List[Tuple[int, int, str]] = Field(default_factory=list)
