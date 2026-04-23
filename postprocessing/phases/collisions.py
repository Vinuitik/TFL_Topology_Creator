"""Phase 1: Resolve IRIs typed as both owl:Class AND owl:NamedIndividual."""
from __future__ import annotations

import logging
from typing import Dict, Set, Tuple

from rdflib import OWL, Graph, URIRef

from utils.graph import get_label, has_number
from utils.llm import call_llm

log = logging.getLogger(__name__)


def phase1_collisions(
    g: Graph,
    protected_iris: Set[URIRef],
    protected_types: Dict[URIRef, Set[URIRef]],
) -> Tuple[Graph, int]:
    classes = {s for s in g.subjects(OWL.Class, None) if isinstance(s, URIRef)}
    # rdflib query: subjects with rdf:type owl:Class
    from rdflib import RDF
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    individuals = {s for s in g.subjects(RDF.type, OWL.NamedIndividual) if isinstance(s, URIRef)}
    collisions = classes & individuals
    resolved = 0

    for iri in collisions:
        label = get_label(g, iri)

        if iri in protected_iris:
            p_types = protected_types.get(iri, set())
            if OWL.Class in p_types:
                g.remove((iri, RDF.type, OWL.NamedIndividual))
            else:
                g.remove((iri, RDF.type, OWL.Class))
            resolved += 1
            continue

        # Digits → individual (no LLM needed)
        if has_number(label):
            declared = "individual"
        else:
            result = call_llm(
                "post_type_judge",
                f'\nName: "{label}"\nDescription: "Entity in the London TfL transport network"\n',
            )
            declared = result.get("type", "individual")

        if declared == "class":
            g.remove((iri, RDF.type, OWL.NamedIndividual))
        else:
            g.remove((iri, RDF.type, OWL.Class))
        resolved += 1
        log.info("Collision: <%s> ('%s') → kept as %s", iri, label, declared)

    log.info("Phase 1: resolved %d collision(s)", resolved)
    return g, resolved
