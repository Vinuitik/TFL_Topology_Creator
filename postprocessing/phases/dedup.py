"""Phases 2/3: Within-type deduplication (DSU + fuzzy + cosine + LLM judge)."""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Set, Tuple

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

from utils.config import POST_DEDUP_OVERRULE_COSINE, POST_ENTITY_SAME_THRESHOLD, POST_FUZZY_THRESHOLD
from utils.embeddings import get_embeddings
from utils.graph import (
    DSU,
    get_label,
    graph_degree,
    is_substring_candidate,
    token_sort_ratio,
    cosine,
)
from utils.llm import call_llm

log = logging.getLogger(__name__)

_DESCRIBE_BATCH = 16  # entities per LLM describe call


def _batch_describe(g: Graph, iris: List[URIRef], labels: Dict[URIRef, str], type_label: str) -> Dict[URIRef, str]:
    """Fetch rdfs:comment for each IRI; batch-generate via LLM for any that are missing."""
    descriptions: Dict[URIRef, str] = {}
    missing: List[URIRef] = []

    for iri in iris:
        comment = next((str(o) for o in g.objects(iri, RDFS.comment)), None)
        if comment:
            descriptions[iri] = comment
        else:
            missing.append(iri)

    if not missing:
        return descriptions

    log.info("Dedup describe: generating descriptions for %d entity/ies", len(missing))
    label_to_iri = {labels[iri]: iri for iri in missing}

    for start in range(0, len(missing), _DESCRIBE_BATCH):
        batch = missing[start : start + _DESCRIBE_BATCH]
        payload = [{"name": labels[iri], "type": type_label} for iri in batch]
        result = call_llm("post_describe", json.dumps(payload, ensure_ascii=False) + "\n")
        for item in result.get("results", []):
            name = str(item.get("name", ""))
            desc = str(item.get("description", ""))
            iri = label_to_iri.get(name)
            if iri and desc:
                descriptions[iri] = desc
                g.add((iri, RDFS.comment, Literal(desc)))

    # Fallback for any still missing
    for iri in missing:
        if iri not in descriptions:
            descriptions[iri] = f"Unknown {type_label} entity."

    return descriptions


_TYPE_LABEL = {
    OWL.Class: "class",
    OWL.NamedIndividual: "individual",
    OWL.ObjectProperty: "object_property",
    OWL.DatatypeProperty: "datatype_property",
    OWL.AnnotationProperty: "annotation_property",
}


def phase_dedup_type(
    g: Graph,
    rdf_type: URIRef,
    category: str,
    protected_iris: Set[URIRef],
) -> Tuple[Dict[URIRef, URIRef], int]:
    iris = [s for s in g.subjects(RDF.type, rdf_type) if isinstance(s, URIRef)]
    if not iris:
        return {}, 0

    labels: Dict[URIRef, str] = {iri: get_label(g, iri) for iri in iris}
    type_label = _TYPE_LABEL.get(rdf_type, "individual")
    log.info("Dedup [%s]: %d entities", type_label, len(iris))

    # Step 1 — fuzzy + substring candidates
    candidates: List[Tuple[URIRef, URIRef]] = []
    for i, a in enumerate(iris):
        for b in iris[i + 1:]:
            if (
                token_sort_ratio(labels[a], labels[b]) >= POST_FUZZY_THRESHOLD
                or is_substring_candidate(labels[a], labels[b])
            ):
                candidates.append((a, b))

    if not candidates:
        log.info("Dedup [%s]: no candidates above threshold %.0f", type_label, POST_FUZZY_THRESHOLD)
        return {}, 0

    log.info("Dedup [%s]: %d candidate pair(s)", type_label, len(candidates))

    # Step 2 — cosine filter
    embeds = get_embeddings(iris, labels, category)
    merge_pairs = [
        (a, b) for a, b in candidates
        if cosine(embeds.get(a, []), embeds.get(b, [])) >= POST_ENTITY_SAME_THRESHOLD
    ]
    log.info(
        "Dedup [%s]: %d pair(s) above cosine %.2f",
        type_label, len(merge_pairs), POST_ENTITY_SAME_THRESHOLD,
    )

    # Step 3 — DSU
    dsu = DSU(iris)
    for a, b in merge_pairs:
        dsu.union(a, b)

    # Step 4 — LLM judge per cluster
    # Pre-collect descriptions for all cluster members (batch-generate missing ones)
    multi_clusters = [list(m) for m in dsu.clusters().values() if len(m) >= 2]
    all_cluster_iris: List[URIRef] = list({m for members in multi_clusters for m in members})
    descriptions = _batch_describe(g, all_cluster_iris, labels, type_label)

    alias_map: Dict[URIRef, URIRef] = {}
    merges = 0
    for members in multi_clusters:
        member_entities = [
            {"name": labels[m], "description": descriptions.get(m, f"Unknown {type_label} entity.")}
            for m in members
        ]
        result = call_llm(
            "post_dedup_judge",
            f"\nInput type: {type_label}\nEntities: {json.dumps(member_entities, ensure_ascii=False)}\n",
        )
        llm_approved = result.get("same", False)

        member_names = [labels[m] for m in members]
        if not llm_approved:
            # Check whether min pairwise cosine exceeds overrule threshold
            member_list = list(members)
            min_cos = min(
                cosine(embeds.get(member_list[i], []), embeds.get(member_list[j], []))
                for i in range(len(member_list))
                for j in range(i + 1, len(member_list))
            )
            if min_cos >= POST_DEDUP_OVERRULE_COSINE:
                log.warning(
                    "Dedup [%s]: OVERRULED LLM rejection for %s (min_cosine=%.3f >= %.3f)",
                    type_label, member_names, min_cos, POST_DEDUP_OVERRULE_COSINE,
                )
            else:
                log.info("Dedup [%s]: LLM rejected merge of %s", type_label, member_names)
                continue

        protected_in = [m for m in members if m in protected_iris]
        canonical = (
            protected_in[0]
            if protected_in
            else max(members, key=lambda m: graph_degree(g, m))
        )
        for m in members:
            if m != canonical:
                alias_map[m] = canonical
                merges += 1
        log.info(
            "Dedup [%s]: merged %d → <%s> ('%s')",
            type_label, len(members) - 1, canonical, labels[canonical],
        )


    log.info("Dedup [%s]: %d total alias(es)", type_label, len(alias_map))
    return alias_map, merges
