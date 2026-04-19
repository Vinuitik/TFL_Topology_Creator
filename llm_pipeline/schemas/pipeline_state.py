from __future__ import annotations

from typing import Any, Dict, List, Literal, TypedDict

from .document import Document, NormalizedDocument, ResolvedDocument
from .entities import Triplet


RouteTarget = Literal[
    "coreference_resolution",
    "extraction",
    "entity_linking",
    "schema_mapping",
    "end",
]


class PipelineState(TypedDict, total=False):
    document: Document
    normalized_document: NormalizedDocument
    resolved_document: ResolvedDocument
    triplets: List[Triplet]
    rag_catalog: Dict[str, Any]
    mapped_graph: Dict[str, Any]
    ontology_draft: Dict[str, List[Dict[str, Any]]]
    inferred_ontology: Dict[str, List[Dict[str, Any]]]
    validated_ontology: Dict[str, List[Dict[str, Any]]]
    validation_errors: List[str]
    validation_report: Dict[str, Any]
    entity_catalog: Dict[str, Any]
    entity_linking_stats: Dict[str, Any]
    inferred_triples_count: int
    linking_conflicts: int
    unmapped_predicates: List[str]
    low_confidence: bool
    missing_relations: bool
    failed_validation: bool
    reroute_target: RouteTarget
    iteration: int
    turtle_output: str
    owl_output: str
    timings: Dict[str, float]
