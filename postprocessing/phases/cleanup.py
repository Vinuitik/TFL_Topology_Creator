"""Phases 5a/5a2/5b: filter long names, bare literals, and clean labels/comments."""
from __future__ import annotations

import logging
import math
import re
from typing import List, Set

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

from ..utils.config import POST_LABEL_LENGTH_STDDEV
from ..utils.graph import get_label

log = logging.getLogger(__name__)

_PAD_RE = re.compile(r"\s*<pad>\s*", re.IGNORECASE)
_WS_RE = re.compile(r"\s{2,}")

_BARE_LITERAL_RE = re.compile(
    r"^("
    r"\d+"                       # pure integer: "42"
    r"|\d{4}[-/]\d{2}[-/]\d{2}" # date: "2024-01-15"
    r"|\d+\.\d+"                 # decimal: "2.50"
    r"|\d+\.\[?\d*\]?"          # garbage: "2003.[96"
    r"|[^\w\s]{2,}"             # only special chars
    r")$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Phase 5a: Long-name filter
# ---------------------------------------------------------------------------

def phase5a_filter_long_names(g: Graph, protected_iris: Set[URIRef]) -> int:
    individuals = [
        s for s in g.subjects(RDF.type, OWL.NamedIndividual)
        if isinstance(s, URIRef) and s not in protected_iris
    ]
    if not individuals:
        return 0

    lengths = [len(get_label(g, ind)) for ind in individuals]
    mean = sum(lengths) / len(lengths)
    std = math.sqrt(sum((l - mean) ** 2 for l in lengths) / len(lengths))
    threshold = mean + POST_LABEL_LENGTH_STDDEV * std

    removed = 0
    for ind, length in zip(individuals, lengths):
        if length > threshold:
            label = get_label(g, ind)
            for t in list(g.triples((ind, None, None))):
                g.remove(t)
            for t in list(g.triples((None, None, ind))):
                g.remove(t)
            removed += 1
            log.info("Long-name removed: '%s' (len=%d > %.0f)", label[:70], length, threshold)

    log.info(
        "Phase 5a: removed %d long-name individual(s) (mean=%.0f std=%.0f threshold=%.0f)",
        removed, mean, std, threshold,
    )
    return removed


# ---------------------------------------------------------------------------
# Phase 5a2: Bare-literal filter
# ---------------------------------------------------------------------------

def phase5a2_filter_bare_literals(g: Graph, protected_iris: Set[URIRef]) -> int:
    removed = 0
    for ind in list(g.subjects(RDF.type, OWL.NamedIndividual)):
        if not isinstance(ind, URIRef) or ind in protected_iris:
            continue
        label = get_label(g, ind).strip()
        if _BARE_LITERAL_RE.match(label):
            for t in list(g.triples((ind, None, None))):
                g.remove(t)
            for t in list(g.triples((None, None, ind))):
                g.remove(t)
            removed += 1
            log.info("Bare-literal removed: '%s'", label)

    log.info("Phase 5a2: removed %d bare-literal individual(s)", removed)
    return removed


# ---------------------------------------------------------------------------
# Phase 5b: Label & comment cleanup
# ---------------------------------------------------------------------------

def _clean_literal(raw: str) -> str:
    cleaned = _PAD_RE.sub(" ", raw)
    return _WS_RE.sub(" ", cleaned).strip()


def phase5b_label_cleanup(g: Graph) -> int:
    ops = 0

    # a) Strip <pad> from all label/comment literals
    for prop in (RDFS.label, RDFS.comment):
        for s, o in list(g.subject_objects(prop)):
            if not isinstance(o, Literal):
                continue
            raw = str(o)
            cleaned = _clean_literal(raw)
            if cleaned != raw:
                g.remove((s, prop, o))
                if cleaned:
                    g.add((s, prop, Literal(cleaned, datatype=o.datatype, lang=o.language or None)))
                ops += 1

    # b) Deduplicate labels and comments (keep longest unique per entity)
    all_entities: List[URIRef] = list({
        s for s in (
            list(g.subjects(RDF.type, OWL.Class))
            + list(g.subjects(RDF.type, OWL.NamedIndividual))
            + list(g.subjects(RDF.type, OWL.ObjectProperty))
            + list(g.subjects(RDF.type, OWL.DatatypeProperty))
        )
        if isinstance(s, URIRef)
    })

    for s in all_entities:
        for prop in (RDFS.label, RDFS.comment):
            vals = list(g.objects(s, prop))
            if len(vals) <= 1:
                continue
            seen: set = set()
            unique = []
            for v in vals:
                key = str(v).lower().strip()
                if key not in seen:
                    seen.add(key)
                    unique.append(v)
            if len(unique) < len(vals):
                for v in vals:
                    g.remove((s, prop, v))
                g.add((s, prop, max(unique, key=lambda v: len(str(v)))))
                ops += 1

    # c) Add missing rdfs:label (CamelCase-split IRI local name)
    for s in all_entities:
        if not any(True for _ in g.objects(s, RDFS.label)):
            local_name = str(s).split("#")[-1].split("/")[-1]
            derived = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local_name).strip()
            if derived:
                g.add((s, RDFS.label, Literal(derived)))
                ops += 1

    log.info("Phase 5b label cleanup: %d operation(s)", ops)
    return ops
