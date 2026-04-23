#!/usr/bin/env python3
"""
KG2 post-processing orchestrator.

Runs the cleaning pipeline against outputs/final.ttl and writes outputs/final_clean.ttl.
No extraction re-run — only deduplication, type correction, label cleanup, and reasoning.

Phase map:
  0  load          Load graph + build protected IRI set from final_ontology.ttl
  1  collisions    Resolve IRIs typed as both owl:Class AND owl:NamedIndividual
  2  class dedup   DSU + fuzzy/substring + cosine + LLM judge (owl:Class bucket)
  3  ind dedup     Same pipeline (owl:NamedIndividual bucket)
  3b obj-prop      Same pipeline (owl:ObjectProperty bucket)
  3c data-prop     Same pipeline (owl:DatatypeProperty bucket)
  4  cross-type    Demote non-protected classes whose label signals an individual
  5  rewrite       Apply alias maps — rewrite all triples to canonical IRIs
  5a long-filter   Remove statistical label-length outliers
  5a2 literal-flt  Remove bare-number / date / garbage individuals
  5b label-clean   Strip <pad>, deduplicate labels/comments, add missing labels
  6  type-repair   Infer rdf:type for orphan individuals from label keywords
  7  reasoning     Inverse/symmetric properties + one-step subClassOf propagation
  8  serialize     Write final_clean.ttl
"""

from __future__ import annotations

import argparse
import logging

from rdflib import OWL

from utils.config import POST_ENTITY_SAME_THRESHOLD, POST_FUZZY_THRESHOLD, POST_LABEL_LENGTH_STDDEV
from utils.graph import log_stats
from phases.load import phase0_load
from phases.collisions import phase1_collisions
from phases.dedup import phase_dedup_type
from phases.cross_type import phase4_cross_type
from phases.rewrite import phase5_rewrite
from phases.cleanup import phase5a_filter_long_names, phase5a2_filter_bare_literals, phase5b_label_cleanup
from phases.type_repair import phase6_type_repair
from phases.reasoning import phase7_reasoning

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="KG2 post-processing: clean and deduplicate final.ttl")
    parser.add_argument("--input", default="/app/outputs/final.ttl")
    parser.add_argument("--ontology", default="/app/inputs/final_ontology.ttl")
    parser.add_argument("--output", default="/app/outputs/final_clean.ttl")
    args = parser.parse_args()

    log.info("=== KG2 Post-Processing ===")
    log.info("Input:    %s", args.input)
    log.info("Ontology: %s", args.ontology)
    log.info("Output:   %s", args.output)
    log.info(
        "Thresholds: cosine=%.2f  fuzzy=%.0f  label_stddev=%.1f",
        POST_ENTITY_SAME_THRESHOLD, POST_FUZZY_THRESHOLD, POST_LABEL_LENGTH_STDDEV,
    )

    # Phase 0
    g, protected_iris, protected_types = phase0_load(args.ontology, args.input)

    # Phase 1 — collision resolution
    g, n_collisions = phase1_collisions(g, protected_iris, protected_types)

    # Phases 2/3 — within-type dedup
    alias_cls, n_cls_merges  = phase_dedup_type(g, OWL.Class,             "entities_class",       protected_iris)
    alias_ind, n_ind_merges  = phase_dedup_type(g, OWL.NamedIndividual,   "entities_individual",  protected_iris)
    alias_obj, n_obj_merges  = phase_dedup_type(g, OWL.ObjectProperty,    "relations_object",     protected_iris)
    alias_dat, n_dat_merges  = phase_dedup_type(g, OWL.DatatypeProperty,  "relations_data",       protected_iris)

    # Phase 4 — cross-type demotion
    g, alias_cross = phase4_cross_type(g, protected_iris)

    # Phase 5 — canonical rewriting
    combined_alias = {**alias_cls, **alias_ind, **alias_obj, **alias_dat, **alias_cross}
    g = phase5_rewrite(g, combined_alias)
    log_stats("After dedup+rewrite", g)

    # Phase 5a — long-name filter
    n_long_removed = phase5a_filter_long_names(g, protected_iris)

    # Phase 5a2 — bare-literal filter
    n_literal_removed = phase5a2_filter_bare_literals(g, protected_iris)

    # Phase 5b — label/comment cleanup
    n_label_ops = phase5b_label_cleanup(g)

    # Phase 6 — type repair
    n_repairs = phase6_type_repair(g)

    # Phase 7 — reasoning
    n_inferred = phase7_reasoning(g)

    # Phase 8 — serialize
    g.serialize(destination=args.output, format="turtle")
    log_stats("Final", g)

    print("\n=== Post-Processing Complete ===")
    print(f"  Collisions resolved  : {n_collisions}")
    print(f"  Class merges         : {n_cls_merges}")
    print(f"  Individual merges    : {n_ind_merges}")
    print(f"  Obj-prop merges      : {n_obj_merges}")
    print(f"  Data-prop merges     : {n_dat_merges}")
    print(f"  Cross-type demotions : {len(alias_cross)}")
    print(f"  Long-name removed    : {n_long_removed}")
    print(f"  Bare-literal removed : {n_literal_removed}")
    print(f"  Label/comment ops    : {n_label_ops}")
    print(f"  Type repairs         : {n_repairs}")
    print(f"  Inferred triples     : {n_inferred}")
    print(f"  Output               : {args.output}")


if __name__ == "__main__":
    main()
