"""Phase 5: Rewrite all triples replacing alias IRIs with canonical IRIs."""
from __future__ import annotations

import logging
from typing import Dict, Set

from rdflib import Graph, URIRef

from utils.graph import copy_namespaces

log = logging.getLogger(__name__)


def phase5_rewrite(g: Graph, alias_map: Dict[URIRef, URIRef]) -> Graph:
    if not alias_map:
        return g

    def _resolve(iri: URIRef) -> URIRef:
        seen: Set[URIRef] = set()
        while iri in alias_map and iri not in seen:
            seen.add(iri)
            iri = alias_map[iri]
        return iri

    resolved = {k: _resolve(k) for k in alias_map}

    new_g = Graph()
    copy_namespaces(g, new_g)
    for s, p, o in g:
        new_s = resolved.get(s, s) if isinstance(s, URIRef) else s
        new_p = resolved.get(p, p) if isinstance(p, URIRef) else p
        new_o = resolved.get(o, o) if isinstance(o, URIRef) else o
        new_g.add((new_s, new_p, new_o))

    log.info(
        "Phase 5 rewrite: %d alias(es), %d → %d triples",
        len(alias_map), len(g), len(new_g),
    )
    return new_g
