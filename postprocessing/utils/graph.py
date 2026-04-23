"""Graph utility helpers: label extraction, fuzzy matching, DSU."""
from __future__ import annotations

import difflib
import math
import re
from typing import Dict, List, Set, Tuple

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef

from utils.config import POST_FUZZY_THRESHOLD

LOCAL = Namespace("http://example.org/tfl#")


# ---------------------------------------------------------------------------
# DSU
# ---------------------------------------------------------------------------

class DSU:
    def __init__(self, items: List) -> None:
        self.p = {x: x for x in items}
        self.rank: Dict = {x: 0 for x in items}

    def find(self, x):
        if self.p[x] != x:
            self.p[x] = self.find(self.p[x])
        return self.p[x]

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def clusters(self) -> Dict:
        out: Dict = {}
        for x in self.p:
            out.setdefault(self.find(x), []).append(x)
        return out


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------

def get_label(g: Graph, iri: URIRef) -> str:
    label = g.value(iri, RDFS.label)
    if label:
        return str(label)
    local_name = str(iri).split("#")[-1].split("/")[-1]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local_name)


def normalize_label(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("_", " ").replace("-", " ")).strip()


def token_sort_ratio(a: str, b: str) -> float:
    a_s = " ".join(sorted(normalize_label(a).split()))
    b_s = " ".join(sorted(normalize_label(b).split()))
    return difflib.SequenceMatcher(None, a_s, b_s).ratio() * 100


def is_substring_candidate(a: str, b: str) -> bool:
    an, bn = normalize_label(a), normalize_label(b)
    return (an in bn or bn in an) and min(len(an), len(bn)) >= 4


def has_number(label: str) -> bool:
    return bool(re.search(r"\d", label))


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def graph_degree(g: Graph, iri: URIRef) -> int:
    return (
        sum(1 for _ in g.triples((iri, None, None)))
        + sum(1 for _ in g.triples((None, None, iri)))
    )


def log_stats(label: str, g: Graph) -> None:
    import logging
    log = logging.getLogger(__name__)
    n_cls = sum(1 for _ in g.subjects(RDF.type, OWL.Class))
    n_ind = sum(1 for _ in g.subjects(RDF.type, OWL.NamedIndividual))
    log.info("%-25s  triples=%-7d  classes=%-5d  individuals=%d", label, len(g), n_cls, n_ind)


def copy_namespaces(src: Graph, dst: Graph) -> None:
    for prefix, ns in src.namespaces():
        dst.bind(prefix, ns)
