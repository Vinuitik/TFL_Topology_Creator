from __future__ import annotations

from typing import Dict, List, Literal, TypedDict

from .document import Document, NormalizedDocument, ResolvedDocument
from .entities import Triplet


RouteTarget = Literal[
    "coreference_resolution",
    "extraction",
    "entity_linking",
    "end",
]


class PipelineState(TypedDict, total=False):
    document: Document
    normalized_document: NormalizedDocument
    resolved_document: ResolvedDocument
    triplets: List[Triplet]
    mapped_graph: Dict[str, List[Dict[str, str]]]
    ontology_draft: Dict[str, List[Dict[str, str]]]
    inferred_ontology: Dict[str, List[Dict[str, str]]]
    validated_ontology: Dict[str, List[Dict[str, str]]]
    validation_errors: List[str]
    low_confidence: bool
    missing_relations: bool
    failed_validation: bool
    reroute_target: RouteTarget
    iteration: int
