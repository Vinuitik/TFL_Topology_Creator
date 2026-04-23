"""Phase 8b: Infer missing object-property triples via cosine similarity + LLM batch."""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Set, Tuple

from rdflib import OWL, RDF, Graph, URIRef

from utils.config import POST_INFER_BATCH_SIZE, POST_INFER_COSINE_THRESHOLD
from utils.embeddings import get_embeddings
from utils.graph import cosine, get_label
from utils.llm import call_llm

log = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.lower())


def _build_prop_map(g: Graph) -> Dict[str, URIRef]:
    """Build normalized label → IRI map for all object properties."""
    result: Dict[str, URIRef] = {}
    for iri in g.subjects(RDF.type, OWL.ObjectProperty):
        if not isinstance(iri, URIRef):
            continue
        lbl = get_label(g, iri)
        result[_normalize(lbl)] = iri
        result[_normalize(lbl.replace(" ", ""))] = iri
    return result


def phase_relation_infer(g: Graph, protected_iris: Set[URIRef]) -> int:
    # Collect all named individuals
    iris: List[URIRef] = [
        s for s in g.subjects(RDF.type, OWL.NamedIndividual)
        if isinstance(s, URIRef)
    ]
    if len(iris) < 2:
        return 0

    labels: Dict[URIRef, str] = {iri: get_label(g, iri) for iri in iris}

    # Fetch / generate embeddings
    embeds = get_embeddings(iris, labels, "entities_individual")
    valid: List[URIRef] = [iri for iri in iris if iri in embeds]
    if len(valid) < 2:
        log.info("Phase relation_infer: too few embeddings, skipping")
        return 0

    prop_map = _build_prop_map(g)

    # O(N²) cosine filter — collect pairs above threshold with no existing link
    candidates: List[Tuple[URIRef, URIRef]] = []
    n = len(valid)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = valid[i], valid[j]
            if (
                next(g.triples((a, None, b)), None) is not None
                or next(g.triples((b, None, a)), None) is not None
            ):
                continue
            sim = cosine(embeds[a], embeds[b])
            if sim >= POST_INFER_COSINE_THRESHOLD:
                candidates.append((a, b))

    if not candidates:
        log.info(
            "Phase relation_infer: no candidate pairs above cosine %.2f",
            POST_INFER_COSINE_THRESHOLD,
        )
        return 0

    log.info(
        "Phase relation_infer: %d candidate pair(s) — batching %d per LLM call",
        len(candidates), POST_INFER_BATCH_SIZE,
    )

    added = 0
    for batch_start in range(0, len(candidates), POST_INFER_BATCH_SIZE):
        batch = candidates[batch_start : batch_start + POST_INFER_BATCH_SIZE]
        pairs_input = [
            {"pair": idx + 1, "a": labels[a], "b": labels[b]}
            for idx, (a, b) in enumerate(batch)
        ]

        result = call_llm(
            "post_relation_infer",
            json.dumps(pairs_input, ensure_ascii=False) + "\n",
        )

        for item in result.get("results", []):
            if not item.get("add"):
                continue

            pair_idx = int(item.get("pair", 0)) - 1
            if pair_idx < 0 or pair_idx >= len(batch):
                continue

            iri_a, iri_b = batch[pair_idx]
            s_label = str(item.get("s", ""))
            p_label = str(item.get("p", ""))
            o_label = str(item.get("o", ""))

            # Resolve subject / object IRIs from the pair
            if _normalize(s_label) == _normalize(labels[iri_a]):
                s_iri, o_iri = iri_a, iri_b
            elif _normalize(s_label) == _normalize(labels[iri_b]):
                s_iri, o_iri = iri_b, iri_a
            else:
                log.warning("relation_infer: cannot resolve subject '%s' — skip", s_label)
                continue

            # Resolve property IRI
            prop_iri = prop_map.get(_normalize(p_label))
            if prop_iri is None:
                log.warning("relation_infer: unknown property '%s' — skip", p_label)
                continue

            # Add only if genuinely new
            if (s_iri, prop_iri, o_iri) not in g:
                g.add((s_iri, prop_iri, o_iri))
                added += 1
                log.info(
                    "relation_infer: + <%s> <%s> <%s>",
                    labels[s_iri], p_label, labels[o_iri],
                )

    log.info("Phase relation_infer: added %d new triple(s)", added)
    return added
