"""Phase 6: Add rdf:type assertions for orphan individuals (no type beyond owl:NamedIndividual)."""
from __future__ import annotations

import logging
from typing import List, Tuple

from rdflib import OWL, RDF, Graph, URIRef

from ..utils.graph import get_label

log = logging.getLogger(__name__)


def phase6_type_repair(g: Graph) -> int:
    # Build class label index, sorted longest-first (greedy best match)
    class_index: List[Tuple[str, URIRef]] = sorted(
        (
            (get_label(g, cls).lower(), cls)
            for cls in g.subjects(RDF.type, OWL.Class)
            if isinstance(cls, URIRef)
        ),
        key=lambda x: -len(x[0]),
    )

    repaired = 0
    for ind in list(g.subjects(RDF.type, OWL.NamedIndividual)):
        if not isinstance(ind, URIRef):
            continue
        types = {t for t in g.objects(ind, RDF.type) if t != OWL.NamedIndividual}
        if types:
            continue
        ind_label = get_label(g, ind).lower()
        for class_label, cls_iri in class_index:
            if class_label in ind_label:
                g.add((ind, RDF.type, cls_iri))
                repaired += 1
                break

    log.info("Phase 6 type repair: %d individual(s) retyped", repaired)
    return repaired
