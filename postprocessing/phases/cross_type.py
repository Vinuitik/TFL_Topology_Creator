"""Phase 4: Demote non-protected class IRIs that should be individuals."""
from __future__ import annotations

import logging
from typing import Dict, Set, Tuple

from rdflib import OWL, RDF, Graph, URIRef

from ..utils.config import POST_FUZZY_THRESHOLD
from ..utils.graph import get_label, has_number, token_sort_ratio
from ..utils.llm import call_llm

log = logging.getLogger(__name__)


def phase4_cross_type(
    g: Graph,
    protected_iris: Set[URIRef],
) -> Tuple[Graph, Dict[URIRef, URIRef]]:
    class_items = [
        (s, get_label(g, s))
        for s in g.subjects(RDF.type, OWL.Class)
        if isinstance(s, URIRef) and s not in protected_iris
    ]
    ind_items = [
        (s, get_label(g, s))
        for s in g.subjects(RDF.type, OWL.NamedIndividual)
        if isinstance(s, URIRef)
    ]

    alias_map: Dict[URIRef, URIRef] = {}
    demoted = 0
    processed: Set[URIRef] = set()

    for cls_iri, cls_label in class_items:
        if cls_iri in processed:
            continue

        if has_number(cls_label):
            is_individual = True
        else:
            result = call_llm(
                "post_type_judge",
                f'\nName: "{cls_label}"\nDescription: "Entity in the London TfL transport network"\n',
            )
            is_individual = result.get("type") == "individual"

        if not is_individual:
            continue

        best_ind: URIRef | None = None
        best_score = 0.0
        for ind_iri, ind_label in ind_items:
            score = token_sort_ratio(cls_label, ind_label)
            if score >= POST_FUZZY_THRESHOLD and score > best_score:
                best_score = score
                best_ind = ind_iri

        if best_ind is not None:
            alias_map[cls_iri] = best_ind
            log.info(
                "Cross-type: demoted class <%s> ('%s') → individual <%s> (score=%.0f)",
                cls_iri, cls_label, best_ind, best_score,
            )
        else:
            g.remove((cls_iri, RDF.type, OWL.Class))
            g.add((cls_iri, RDF.type, OWL.NamedIndividual))
            log.info("Cross-type: demoted class <%s> ('%s') in-place", cls_iri, cls_label)

        processed.add(cls_iri)
        demoted += 1

    log.info("Phase 4: %d class(es) demoted", demoted)
    return g, alias_map
