"""Phase 8b: Infer missing object-property triples via cosine similarity + LLM batch."""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Dict, List, Set, Tuple

from rdflib import OWL, RDF, Graph, URIRef


from utils.config import (
    POST_INFER_BATCH_SIZE,
    POST_INFER_COSINE_THRESHOLD,
    POST_MAX_WORKERS,
    POST_PHASE_TIMEOUT_MINS,
)
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
    start_time = time.time()
    limit_sec = POST_PHASE_TIMEOUT_MINS * 60
    
    batches = [
        candidates[i : i + POST_INFER_BATCH_SIZE]
        for i in range(0, len(candidates), POST_INFER_BATCH_SIZE)
    ]
    total_batches = len(batches)
    log.info("Phase relation_infer: processing %d batch(es) with %d workers...", total_batches, POST_MAX_WORKERS)

    def _process_batch(batch_idx, batch):
        pairs_input = [
            {"pair": idx + 1, "a": labels[a], "b": labels[b]}
            for idx, (a, b) in enumerate(batch)
        ]
        res = call_llm(
            "post_relation_infer",
            json.dumps(pairs_input, ensure_ascii=False) + "\n",
        )
        return batch_idx, batch, res

    pool = ThreadPoolExecutor(max_workers=POST_MAX_WORKERS)
    future_to_meta = {
        pool.submit(_process_batch, idx, batch): (idx, batch)
        for idx, batch in enumerate(batches)
    }
    pending = set(future_to_meta.keys())
    processed = 0
    last_heartbeat = start_time

    try:
        while pending:
            elapsed = time.time() - start_time
            remaining = limit_sec - elapsed
            if remaining <= 0:
                log.warning(
                    "Phase relation_infer: timeout reached (%d mins) — skipping remaining %d batch(es)",
                    POST_PHASE_TIMEOUT_MINS,
                    len(pending),
                )
                break

            done, pending = wait(
                pending,
                timeout=min(1.0, remaining),
                return_when=FIRST_COMPLETED,
            )
            if not done:
                now = time.time()
                if now - last_heartbeat >= 30:
                    log.info(
                        "Phase relation_infer: waiting... processed %d/%d batch(es), elapsed %.1f min, remaining %.1f min",
                        processed,
                        total_batches,
                        elapsed / 60.0,
                        max(remaining, 0) / 60.0,
                    )
                    last_heartbeat = now
                continue

            for fut in done:
                batch_idx, batch = future_to_meta[fut]
                processed += 1
                try:
                    _, _, result = fut.result()
                except Exception as exc:
                    log.warning("relation_infer: batch %d failed: %s", batch_idx + 1, exc)
                    continue

                # Progress bar
                if total_batches > 0:
                    pct = processed / total_batches
                    filled = int(20 * pct)
                    bar = "#" * filled + "." * (20 - filled)
                    if processed % max(1, total_batches // 10) == 0 or processed == total_batches:
                        log.info("Relation Infer progress: [%s] %.0f%%", bar, pct * 100)

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

                    # Resolve subject / object IRIs from the pair (exact then substring fallback)
                    norm_s = _normalize(s_label)
                    norm_a = _normalize(labels[iri_a])
                    norm_b = _normalize(labels[iri_b])
                    if norm_s == norm_a or norm_s in norm_a or norm_a in norm_s:
                        s_iri, o_iri = iri_a, iri_b
                    elif norm_s == norm_b or norm_s in norm_b or norm_b in norm_s:
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
    finally:
        for fut in pending:
            fut.cancel()
        pool.shutdown(wait=False, cancel_futures=True)

    log.info("Phase relation_infer: added %d new triple(s)", added)
    return added
