"""Phase 4b: Remove owl:Class entities with no UK public transport relevance."""
from __future__ import annotations

import json
import logging
from typing import Set

from rdflib import OWL, RDF, Graph, URIRef

from utils.config import POST_DOMAIN_FILTER_BATCH
from utils.graph import get_label
from utils.llm import call_llm

log = logging.getLogger(__name__)


def phase_domain_filter(g: Graph, protected_iris: Set[URIRef]) -> int:
    candidates = [
        (s, get_label(g, s))
        for s in g.subjects(RDF.type, OWL.Class)
        if isinstance(s, URIRef) and s not in protected_iris
    ]
    if not candidates:
        log.info("Phase 4b domain filter: no unprotected classes to check")
        return 0

    label_to_iri: dict[str, URIRef] = {label: iri for iri, label in candidates}
    all_labels = list(label_to_iri.keys())

    irrelevant: set[str] = set()
    for i in range(0, len(all_labels), POST_DOMAIN_FILTER_BATCH):
        batch = all_labels[i : i + POST_DOMAIN_FILTER_BATCH]
        result = call_llm("post_domain_filter", json.dumps(batch, ensure_ascii=False) + "\n")
        for label in result.get("irrelevant", []):
            if isinstance(label, str):
                irrelevant.add(label)

    removed = 0
    for label in irrelevant:
        iri = label_to_iri.get(label)
        if iri is None or iri in protected_iris:
            continue
        for t in list(g.triples((iri, None, None))):
            g.remove(t)
        for t in list(g.triples((None, None, iri))):
            g.remove(t)
        removed += 1
        log.info("Domain filter: removed class '%s' <%s>", label, iri)

    log.info(
        "Phase 4b domain filter: checked %d class(es), removed %d out-of-domain",
        len(candidates), removed,
    )
    return removed
