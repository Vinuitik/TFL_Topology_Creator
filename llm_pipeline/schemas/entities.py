from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class Entity(BaseModel):
    id: str
    type: str
    mentions: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class CanonicalEntity(BaseModel):
    id: str
    canonical_name: str
    type: str
    aliases: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class Relation(BaseModel):
    id: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = 0.0
    provenance_sentence: str = ""


class Attribute(BaseModel):
    id: str
    entity_id: str
    key: str
    value: str
    datatype: str = "string"
    confidence: float = 0.0
    provenance_sentence: str = ""
