"""Phase 7: Infer triples via inverse/symmetric properties and one-step subClassOf."""
from __future__ import annotations

import logging
from typing import Dict, List

from rdflib import OWL, RDF, RDFS, Graph, URIRef

log = logging.getLogger(__name__)


def phase7_reasoning(g: Graph) -> int:
    new_triples: set = set()

    # Inverse properties
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        inverse = g.value(prop, OWL.inverseOf)
        if inverse:
            for s, o in g.subject_objects(prop):
                if isinstance(s, URIRef) and isinstance(o, URIRef):
                    new_triples.add((o, inverse, s))

    # Symmetric properties
    for prop in g.subjects(RDF.type, OWL.SymmetricProperty):
        for s, o in g.subject_objects(prop):
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                new_triples.add((o, prop, s))

    # One-step subClassOf type propagation
    subclass_map: Dict[URIRef, List[URIRef]] = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef):
            sups = [
                sup for sup in g.objects(cls, RDFS.subClassOf)
                if isinstance(sup, URIRef) and sup != OWL.Thing
            ]
            if sups:
                subclass_map[cls] = sups

    for ind in g.subjects(RDF.type, OWL.NamedIndividual):
        for cls in list(g.objects(ind, RDF.type)):
            if isinstance(cls, URIRef):
                for sup in subclass_map.get(cls, []):
                    new_triples.add((ind, RDF.type, sup))

    added = sum(1 for t in new_triples if t not in g)
    for t in new_triples:
        g.add(t)

    log.info("Phase 7 reasoning: %d new triple(s) inferred", added)
    return added
