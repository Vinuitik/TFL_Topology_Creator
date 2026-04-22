#!/usr/bin/env python3
"""
Post-processing: deduplicate and clean outputs/final.ttl → outputs/final_clean.ttl.

Phases:
  1. Load & anchor  (protected IRIs from final_ontology.ttl)
  2. Collision      (same IRI typed as both owl:Class AND owl:NamedIndividual)
  3. Class dedup    (within-class DSU + fuzzy + cosine + LLM judge)
  4. Individual dedup (same pipeline, individual bucket)
  5. Cross-type     (class IRI whose label matches an individual → demote class)
  6. Rewrite        (apply alias maps — all triples rewritten to canonical IRIs)
  7. Type repair    (orphan individuals infer rdf:type from label keyword match)
  8. Reasoning      (inverses, symmetry, one-step subClassOf propagation)
  9. Serialize      → outputs/final_clean.ttl

Prompts loaded from postprocessing/prompts/ — never from llm_pipeline/prompts/.
Thresholds: POST_ENTITY_SAME_THRESHOLD (cosine), POST_FUZZY_THRESHOLD (token-sort-ratio).
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Set, Tuple

import redis
import requests
from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOCAL = Namespace("http://example.org/tfl#")
PROMPTS_DIR = Path(__file__).parent / "prompts"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://ollama:11434/api/embeddings")
OLLAMA_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL", "qwen2.5:3b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.3"))
OLLAMA_SEED = int(os.getenv("OLLAMA_SEED", "42"))
OLLAMA_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC", "3600"))
OLLAMA_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))
EMBED_WORKERS = int(os.getenv("EMBED_WORKERS", "4"))

POST_ENTITY_SAME_THRESHOLD = float(os.getenv("POST_ENTITY_SAME_THRESHOLD", "0.75"))
POST_FUZZY_THRESHOLD = float(os.getenv("POST_FUZZY_THRESHOLD", "88"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DSU  (self-contained copy — does not import from llm_pipeline)
# ---------------------------------------------------------------------------

class _DSU:
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
# Redis
# ---------------------------------------------------------------------------

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# ---------------------------------------------------------------------------
# LLM client  (self-contained; loads from PROMPTS_DIR)
# ---------------------------------------------------------------------------

def _find_latest_prompt(name: str) -> Path:
    matches = list(PROMPTS_DIR.glob(f"{name}-v*.txt"))
    if not matches:
        raise FileNotFoundError(f"No prompt for '{name}' in {PROMPTS_DIR}")

    def _ver(p: Path) -> int:
        m = re.search(r"-v(\d+)\.txt$", p.name)
        return int(m.group(1)) if m else -1

    return max(matches, key=_ver)


def _parse_json(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    stripped = raw.strip()
    if stripped.startswith("{"):
        ob = stripped.count("{") - stripped.count("}")
        oq = stripped.count("[") - stripped.count("]")
        candidate = stripped.rstrip(", \t\n\r")
        suffix = "]" * max(oq, 0) + "}" * max(ob, 0)
        for closing in [suffix, "]}", "}", ""]:
            try:
                return json.loads(candidate + closing)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Cannot parse JSON from: {raw[:200]}")


def call_llm(prompt_name: str, params: str) -> dict:
    try:
        prompt_path = _find_latest_prompt(prompt_name)
    except FileNotFoundError as exc:
        log.warning("Prompt missing: %s", exc)
        return {}

    full_prompt = prompt_path.read_text(encoding="utf-8") + params
    payload = {
        "model": OLLAMA_ENTITY_MODEL,
        "prompt": full_prompt,
        "stream": True,
        "format": "json",
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "seed": OLLAMA_SEED,
            "repeat_penalty": 1.15,
        },
    }

    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        payload["options"]["seed"] = OLLAMA_SEED + attempt - 1
        accumulated = ""
        try:
            with requests.post(
                OLLAMA_URL, json=payload, stream=True, timeout=OLLAMA_TIMEOUT_SEC
            ) as resp:
                resp.raise_for_status()
                deadline = time.monotonic() + OLLAMA_TIMEOUT_SEC
                for line in resp.iter_lines():
                    if time.monotonic() > deadline:
                        log.warning("LLM stream timeout for %s attempt %d", prompt_name, attempt)
                        break
                    if line:
                        chunk = json.loads(line)
                        accumulated += chunk.get("response", "")
                        if chunk.get("done"):
                            break
        except requests.RequestException as exc:
            log.warning("LLM request error (%s attempt %d): %s", prompt_name, attempt, exc)
            if attempt < OLLAMA_MAX_RETRIES:
                continue
            return {}

        try:
            return _parse_json(accumulated)
        except ValueError:
            if attempt < OLLAMA_MAX_RETRIES:
                log.warning("LLM bad JSON for %s attempt %d — retrying", prompt_name, attempt)
                continue
            log.warning("LLM JSON parse failed for %s — returning {}", prompt_name)
            return {}

    return {}


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def _embed(text: str) -> List[float]:
    for attempt in range(3):
        try:
            r = requests.post(
                OLLAMA_EMBED_URL,
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
                timeout=OLLAMA_TIMEOUT_SEC,
            )
            r.raise_for_status()
            return r.json().get("embedding", [])
        except Exception as exc:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
            else:
                log.warning("Embed failed for '%s': %s", text[:40], exc)
    return []


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def _get_embeddings(
    iris: List[URIRef], labels: Dict[URIRef, str], category: str
) -> Dict[URIRef, List[float]]:
    r = _get_redis()
    embeds: Dict[URIRef, List[float]] = {}
    needs_embed: List[URIRef] = []

    for iri in iris:
        label = labels[iri]
        found = False
        for key in (
            f"{category}:emb:{label}",
            f"entities:emb:{label}",
            f"relations:emb:{label}",
            f"entities_class:emb:{label}",
            f"entities_individual:emb:{label}",
        ):
            raw = r.get(key)
            if raw:
                try:
                    embeds[iri] = json.loads(raw)
                    found = True
                    break
                except json.JSONDecodeError:
                    pass
        if not found:
            needs_embed.append(iri)

    if needs_embed:
        log.info("Generating %d embedding(s) not found in Redis (category=%s)...", len(needs_embed), category)

        def _do(iri: URIRef) -> Tuple[URIRef, List[float]]:
            return iri, _embed(labels[iri])

        with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
            for iri, emb in pool.map(_do, needs_embed):
                if emb:
                    embeds[iri] = emb

    return embeds


# ---------------------------------------------------------------------------
# Label / graph utilities
# ---------------------------------------------------------------------------

def _get_label(g: Graph, iri: URIRef) -> str:
    label = g.value(iri, RDFS.label)
    if label:
        return str(label)
    local_name = str(iri).split("#")[-1].split("/")[-1]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local_name)


def _token_sort_ratio(a: str, b: str) -> float:
    """Token-sort similarity 0–100. Equivalent to rapidfuzz.fuzz.token_sort_ratio."""
    a_s = " ".join(sorted(a.lower().split()))
    b_s = " ".join(sorted(b.lower().split()))
    return difflib.SequenceMatcher(None, a_s, b_s).ratio() * 100


def _graph_degree(g: Graph, iri: URIRef) -> int:
    return (
        sum(1 for _ in g.triples((iri, None, None)))
        + sum(1 for _ in g.triples((None, None, iri)))
    )


def _log_stats(label: str, g: Graph) -> None:
    n_cls = sum(1 for _ in g.subjects(RDF.type, OWL.Class))
    n_ind = sum(1 for _ in g.subjects(RDF.type, OWL.NamedIndividual))
    log.info(
        "%-25s  triples=%-7d  classes=%-5d  individuals=%d",
        label, len(g), n_cls, n_ind,
    )


def _copy_namespaces(src: Graph, dst: Graph) -> None:
    for prefix, ns in src.namespaces():
        dst.bind(prefix, ns)


# ---------------------------------------------------------------------------
# Phase 0: Load & anchor
# ---------------------------------------------------------------------------

def phase0_load(
    ontology_path: str, input_path: str
) -> Tuple[Graph, Set[URIRef], Dict[URIRef, Set[URIRef]]]:
    pg = Graph()
    pg.parse(ontology_path, format="turtle")

    protected_iris: Set[URIRef] = set()
    protected_types: Dict[URIRef, Set[URIRef]] = {}
    for s in pg.subjects():
        if isinstance(s, URIRef):
            protected_iris.add(s)
            ts = set(pg.objects(s, RDF.type))
            if ts:
                protected_types[s] = ts

    log.info("Protected IRIs: %d (from %s)", len(protected_iris), ontology_path)

    g = Graph()
    g.parse(input_path, format="turtle")
    _log_stats("Initial graph", g)
    return g, protected_iris, protected_types


# ---------------------------------------------------------------------------
# Phase 1: Collision resolution
# ---------------------------------------------------------------------------

def phase1_collisions(
    g: Graph,
    protected_iris: Set[URIRef],
    protected_types: Dict[URIRef, Set[URIRef]],
) -> Tuple[Graph, int]:
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    individuals = {s for s in g.subjects(RDF.type, OWL.NamedIndividual) if isinstance(s, URIRef)}
    collisions = classes & individuals
    resolved = 0

    for iri in collisions:
        label = _get_label(g, iri)
        if iri in protected_iris:
            p_types = protected_types.get(iri, set())
            if OWL.Class in p_types:
                g.remove((iri, RDF.type, OWL.NamedIndividual))
            else:
                g.remove((iri, RDF.type, OWL.Class))
            resolved += 1
            continue

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
        log.info("Phase 1 collision: <%s> ('%s') → kept as %s", iri, label, declared)

    log.info("Phase 1: resolved %d collision(s)", resolved)
    return g, resolved


# ---------------------------------------------------------------------------
# Phase 2/3: Within-type deduplication
# ---------------------------------------------------------------------------

def phase_dedup_type(
    g: Graph,
    rdf_type: URIRef,
    category: str,
    protected_iris: Set[URIRef],
) -> Tuple[Dict[URIRef, URIRef], int]:
    iris = [s for s in g.subjects(RDF.type, rdf_type) if isinstance(s, URIRef)]
    if not iris:
        return {}, 0

    labels: Dict[URIRef, str] = {iri: _get_label(g, iri) for iri in iris}
    type_label = "class" if rdf_type == OWL.Class else "individual"
    log.info("Dedup [%s]: %d entities", type_label, len(iris))

    # Step 1 — fuzzy candidate pairs
    candidates: List[Tuple[URIRef, URIRef]] = []
    for i, a in enumerate(iris):
        for b in iris[i + 1:]:
            if _token_sort_ratio(labels[a], labels[b]) >= POST_FUZZY_THRESHOLD:
                candidates.append((a, b))

    if not candidates:
        log.info("Dedup [%s]: no fuzzy candidates above %.0f", type_label, POST_FUZZY_THRESHOLD)
        return {}, 0

    log.info("Dedup [%s]: %d fuzzy candidate pair(s)", type_label, len(candidates))

    # Step 2 — embedding cosine filter
    embeds = _get_embeddings(iris, labels, category)
    merge_pairs = [
        (a, b) for a, b in candidates
        if _cosine(embeds.get(a, []), embeds.get(b, [])) >= POST_ENTITY_SAME_THRESHOLD
    ]
    log.info(
        "Dedup [%s]: %d pair(s) above cosine threshold %.2f",
        type_label, len(merge_pairs), POST_ENTITY_SAME_THRESHOLD,
    )

    # Step 3 — DSU
    dsu = _DSU(iris)
    for a, b in merge_pairs:
        dsu.union(a, b)

    # Step 4 — LLM judge per cluster
    alias_map: Dict[URIRef, URIRef] = {}
    merges = 0
    for members in dsu.clusters().values():
        if len(members) < 2:
            continue
        member_labels = [labels[m] for m in members]
        result = call_llm(
            "post_dedup_judge",
            f"\nInput type: {type_label}\nNames: {json.dumps(member_labels)}\n",
        )
        if not result.get("same", False):
            log.info("Dedup [%s]: LLM rejected merge of %s", type_label, member_labels)
            continue

        # canonical: protected wins, then highest degree
        protected_in = [m for m in members if m in protected_iris]
        canonical = (
            protected_in[0]
            if protected_in
            else max(members, key=lambda m: _graph_degree(g, m))
        )
        for m in members:
            if m != canonical:
                alias_map[m] = canonical
                merges += 1
        log.info(
            "Dedup [%s]: merged %d alias(es) → <%s> ('%s')",
            type_label, len(members) - 1, canonical, labels[canonical],
        )

    log.info("Dedup [%s]: %d total alias(es)", type_label, len(alias_map))
    return alias_map, merges


# ---------------------------------------------------------------------------
# Phase 4: Cross-type resolution
# ---------------------------------------------------------------------------

def phase4_cross_type(
    g: Graph,
    protected_iris: Set[URIRef],
) -> Tuple[Graph, Dict[URIRef, URIRef]]:
    """Demote non-protected class IRIs whose label resembles an individual's label."""
    class_items = [
        (s, _get_label(g, s))
        for s in g.subjects(RDF.type, OWL.Class)
        if isinstance(s, URIRef) and s not in protected_iris
    ]
    ind_items = [
        (s, _get_label(g, s))
        for s in g.subjects(RDF.type, OWL.NamedIndividual)
        if isinstance(s, URIRef)
    ]

    alias_map: Dict[URIRef, URIRef] = {}
    demoted = 0
    processed: Set[URIRef] = set()

    for cls_iri, cls_label in class_items:
        if cls_iri in processed:
            continue

        # Check if LLM thinks this label represents an individual
        result = call_llm(
            "post_type_judge",
            f'\nName: "{cls_label}"\nDescription: "Entity in the London TfL transport network"\n',
        )
        if result.get("type") != "individual":
            continue

        # Find the best-matching individual by fuzzy score
        best_ind: URIRef | None = None
        best_score = 0.0
        for ind_iri, ind_label in ind_items:
            score = _token_sort_ratio(cls_label, ind_label)
            if score >= POST_FUZZY_THRESHOLD and score > best_score:
                best_score = score
                best_ind = ind_iri

        if best_ind is not None:
            # Merge: class IRI → individual IRI
            alias_map[cls_iri] = best_ind
            log.info(
                "Phase 4: demoted class <%s> ('%s') → individual <%s> (score=%.0f)",
                cls_iri, cls_label, best_ind, best_score,
            )
        else:
            # No matching individual: demote in-place (class IRI becomes an individual)
            g.remove((cls_iri, RDF.type, OWL.Class))
            g.add((cls_iri, RDF.type, OWL.NamedIndividual))
            log.info(
                "Phase 4: demoted class <%s> ('%s') in-place (no matching individual found)",
                cls_iri, cls_label,
            )

        processed.add(cls_iri)
        demoted += 1

    log.info("Phase 4: %d class(es) demoted to individual", demoted)
    return g, alias_map


# ---------------------------------------------------------------------------
# Phase 5: Canonical rewriting
# ---------------------------------------------------------------------------

def phase5_rewrite(g: Graph, alias_map: Dict[URIRef, URIRef]) -> Graph:
    if not alias_map:
        return g

    # Resolve chains: alias → canonical → (no further alias)
    def _resolve(iri: URIRef) -> URIRef:
        seen: Set[URIRef] = set()
        while iri in alias_map and iri not in seen:
            seen.add(iri)
            iri = alias_map[iri]
        return iri

    resolved: Dict[URIRef, URIRef] = {k: _resolve(k) for k in alias_map}

    new_g = Graph()
    _copy_namespaces(g, new_g)
    for s, p, o in g:
        new_s = resolved.get(s, s) if isinstance(s, URIRef) else s
        new_p = resolved.get(p, p) if isinstance(p, URIRef) else p
        new_o = resolved.get(o, o) if isinstance(o, URIRef) else o
        new_g.add((new_s, new_p, new_o))

    log.info(
        "Phase 5 rewrite: %d alias(es) applied, %d → %d triples",
        len(alias_map), len(g), len(new_g),
    )
    return new_g


# ---------------------------------------------------------------------------
# Phase 5b: Label & comment cleanup
# ---------------------------------------------------------------------------

_PAD_RE = re.compile(r"\s*<pad>\s*", re.IGNORECASE)
_WS_RE = re.compile(r"\s{2,}")


def _clean_literal(raw: str) -> str:
    cleaned = _PAD_RE.sub(" ", raw)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned


def phase5b_label_cleanup(g: Graph) -> int:
    """
    Three passes:
      a) Strip <pad> tokens from rdfs:label and rdfs:comment literals.
      b) Deduplicate: multiple labels/comments on the same entity → keep longest unique.
      c) Add missing rdfs:label: derive from IRI CamelCase local name.
    """
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
                    g.add((s, prop, Literal(cleaned, datatype=o.datatype, lang=o.language if o.language else None)))
                ops += 1

    # b) Deduplicate labels and comments per entity
    all_entities = [
        s for s in set(
            list(g.subjects(RDF.type, OWL.Class))
            + list(g.subjects(RDF.type, OWL.NamedIndividual))
            + list(g.subjects(RDF.type, OWL.ObjectProperty))
            + list(g.subjects(RDF.type, OWL.DatatypeProperty))
        )
        if isinstance(s, URIRef)
    ]

    for s in all_entities:
        for prop in (RDFS.label, RDFS.comment):
            vals = list(g.objects(s, prop))
            if len(vals) <= 1:
                continue
            seen: set = set()
            unique: list = []
            for v in vals:
                key = str(v).lower().strip()
                if key not in seen:
                    seen.add(key)
                    unique.append(v)
            if len(unique) < len(vals):
                for v in vals:
                    g.remove((s, prop, v))
                best = max(unique, key=lambda v: len(str(v)))
                g.add((s, prop, best))
                ops += 1

    # c) Add missing rdfs:label (derive from IRI local name)
    for s in all_entities:
        if not any(True for _ in g.objects(s, RDFS.label)):
            local_name = str(s).split("#")[-1].split("/")[-1]
            derived = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local_name).strip()
            if derived:
                g.add((s, RDFS.label, Literal(derived)))
                ops += 1

    log.info("Phase 5b label cleanup: %d operation(s)", ops)
    return ops


# ---------------------------------------------------------------------------
# Phase 6: Type repair
# ---------------------------------------------------------------------------

def phase6_type_repair(g: Graph) -> int:
    # Build index: class_label_lower → class_IRI, sorted longest-first for best match
    class_index: List[Tuple[str, URIRef]] = sorted(
        ((_get_label(g, cls).lower(), cls) for cls in g.subjects(RDF.type, OWL.Class) if isinstance(cls, URIRef)),
        key=lambda x: -len(x[0]),
    )

    repaired = 0
    for ind in list(g.subjects(RDF.type, OWL.NamedIndividual)):
        if not isinstance(ind, URIRef):
            continue
        types = {t for t in g.objects(ind, RDF.type) if t != OWL.NamedIndividual}
        if types:
            continue

        ind_label = _get_label(g, ind).lower()
        for class_label, cls_iri in class_index:
            if class_label in ind_label:
                g.add((ind, RDF.type, cls_iri))
                repaired += 1
                break

    log.info("Phase 6 type repair: %d individual(s) retyped", repaired)
    return repaired


# ---------------------------------------------------------------------------
# Phase 7: Reasoning
# ---------------------------------------------------------------------------

def phase7_reasoning(g: Graph) -> int:
    new_triples: set = set()

    # Inverse properties
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        inverse = g.value(prop, OWL.inverseOf)
        if inverse:
            for s, o in g.subject_objects(prop):
                if isinstance(s, URIRef) and isinstance(o, URIRef):
                    new_triples.add((o, inverse, s))

    # Symmetric properties
    for prop in g.subjects(RDF.type, OWL.SymmetricProperty):
        for s, o in g.subject_objects(prop):
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                new_triples.add((o, prop, s))

    # One-step subClassOf type propagation
    subclass_map: Dict[URIRef, List[URIRef]] = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef):
            sups = [
                sup for sup in g.objects(cls, RDFS.subClassOf)
                if isinstance(sup, URIRef) and sup != OWL.Thing
            ]
            if sups:
                subclass_map[cls] = sups

    for ind in g.subjects(RDF.type, OWL.NamedIndividual):
        for cls in list(g.objects(ind, RDF.type)):
            if isinstance(cls, URIRef):
                for sup in subclass_map.get(cls, []):
                    new_triples.add((ind, RDF.type, sup))

    added = 0
    for t in new_triples:
        if t not in g:
            g.add(t)
            added += 1

    log.info("Phase 7 reasoning: %d new triple(s) inferred", added)
    return added


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="KG2 post-processing: deduplicate and clean final.ttl")
    parser.add_argument("--input", default="/app/outputs/final.ttl", help="Input TTL file")
    parser.add_argument("--ontology", default="/app/inputs/final_ontology.ttl", help="Protected ontology TTL")
    parser.add_argument("--output", default="/app/outputs/final_clean.ttl", help="Output TTL file")
    args = parser.parse_args()

    log.info("=== KG2 Post-Processing ===")
    log.info("Input:    %s", args.input)
    log.info("Ontology: %s", args.ontology)
    log.info("Output:   %s", args.output)
    log.info(
        "Thresholds: cosine=%.2f  fuzzy=%.0f",
        POST_ENTITY_SAME_THRESHOLD, POST_FUZZY_THRESHOLD,
    )

    # Phase 0
    g, protected_iris, protected_types = phase0_load(args.ontology, args.input)

    # Phase 1 — collision resolution
    g, n_collisions = phase1_collisions(g, protected_iris, protected_types)

    # Phase 2 — class dedup
    alias_cls, n_cls_merges = phase_dedup_type(g, OWL.Class, "entities_class", protected_iris)

    # Phase 3 — individual dedup
    alias_ind, n_ind_merges = phase_dedup_type(g, OWL.NamedIndividual, "entities_individual", protected_iris)

    # Phase 4 — cross-type demotion
    g, alias_cross = phase4_cross_type(g, protected_iris)

    # Phase 5 — canonical rewriting
    combined_alias = {**alias_cls, **alias_ind, **alias_cross}
    g = phase5_rewrite(g, combined_alias)
    _log_stats("After dedup+rewrite", g)

    # Phase 5b — label / comment cleanup
    n_label_ops = phase5b_label_cleanup(g)

    # Phase 6 — type repair
    n_repairs = phase6_type_repair(g)

    # Phase 7 — reasoning
    n_inferred = phase7_reasoning(g)

    # Phase 8 — serialize
    g.serialize(destination=args.output, format="turtle")
    _log_stats("Final", g)

    print("\n=== Post-Processing Complete ===")
    print(f"  Collisions resolved : {n_collisions}")
    print(f"  Class merges        : {n_cls_merges}")
    print(f"  Individual merges   : {n_ind_merges}")
    print(f"  Cross-type demotions: {len(alias_cross)}")
    print(f"  Label/comment ops   : {n_label_ops}")
    print(f"  Type repairs        : {n_repairs}")
    print(f"  Inferred triples    : {n_inferred}")
    print(f"  Output              : {args.output}")


if __name__ == "__main__":
    main()
