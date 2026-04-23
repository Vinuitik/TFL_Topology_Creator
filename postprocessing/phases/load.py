"""Phase 0: Load graph and build protected IRI set from final_ontology.ttl."""
from __future__ import annotations

import logging
from typing import Dict, Set, Tuple

from rdflib import OWL, RDF, Graph, URIRef

from ..utils.graph import log_stats

log = logging.getLogger(__name__)


def phase0_load(
    ontology_path: str, input_path: str
) -> Tuple[Graph, Set[URIRef], Dict[URIRef, Set[URIRef]]]:
    pg = Graph()
    pg.parse(ontology_path, format="turtle")

    protected_iris: Set[URIRef] = set()
    protected_types: Dict[URIRef, Set[URIRef]] = {}
    for s in pg.subjects():
        if isinstance(s, URIRef):
            protected_iris.add(s)
            ts = set(pg.objects(s, RDF.type))
            if ts:
                protected_types[s] = ts

    log.info("Protected IRIs: %d (from %s)", len(protected_iris), ontology_path)

    g = Graph()
    g.parse(input_path, format="turtle")
    log_stats("Initial graph", g)
    return g, protected_iris, protected_types
