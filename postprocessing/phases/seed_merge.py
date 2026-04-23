"""Phase 9: Merge tfl_seed.ttl into the cleaned graph."""
from __future__ import annotations

import logging
from pathlib import Path

from rdflib import Graph

log = logging.getLogger(__name__)


def phase9_seed_merge(g: Graph, seed_path: str) -> int:
    p = Path(seed_path)
    if not p.exists():
        log.warning("Seed file not found: %s — skipping", seed_path)
        return 0

    seed = Graph()
    seed.parse(str(p), format="turtle")

    before = len(g)
    for triple in seed:
        g.add(triple)

    added = len(g) - before
    log.info("Phase 9 seed merge: added %d triple(s) from %s", added, p.name)
    return added
