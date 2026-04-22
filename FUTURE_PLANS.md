# Future Pipeline Improvements

## 1. Provenance Metadata (manual vs pipeline)

**Goal:** Tag every entity and relation with its origin so pipeline-generated content can be identified and selectively removed later.

**Design:**
- Add `source` field to `entity_catalog` entries: `"manual"` | `"pipeline"` | `"pipeline_inferred"`
- `ingest_owl.py` tags everything it writes to Redis as `source: "manual"`
- `entity_classification` tags new entries as `source: "pipeline"`
- `individual_labeling` (see §3) tags inferred type assertions as `source: "pipeline_inferred"`
- Emit as a custom OWL annotation property (e.g. `kg:source`) in `ontology_construction`

**Chain-delete utility:**
- Find all `pipeline` classes → find all individuals whose only `rdf:type` points to those classes → remove both
- Lives as a standalone rdflib utility function, callable post-serialization

---

## 2. Triplet Pruning

**Goal:** Filter low-quality or nonsensical triplets before they propagate downstream.

**Placement:** After `extraction`, before `entity_classification` — avoids wasting LLM classification calls on garbage.

**Design:**
- Batch triplets to LLM with prompt: "Score this triplet 1–3: does it represent a real, meaningful relationship? 1=nonsense, 2=uncertain, 3=valid"
- Threshold controlled by env var `PRUNE_MIN_SCORE` (default: 2)
- Below threshold: log as WARNING and drop
- At threshold: keep but tag with low confidence (future use)
- Start with log-only mode (no actual deletion) to tune threshold before enabling hard prune

**Risk:** False positives — unusual but valid triplets may score low. Audit logged drops before lowering threshold.

---

## 3. Individual Labeling (class assignment for untyped individuals)

**Goal:** Every `owl:NamedIndividual` should have at least one `rdf:type` pointing to a class. Currently, REBEL-extracted individuals not caught by spaCy NER are floating with no class membership.

**Placement:** After `entity_linking`, before `schema_mapping`.

**Design:**
- Collect all `individual` entities with no existing `type` triplet pointing to a `class` entity
- Phase 1 — embedding similarity: embed individual name → cosine against all known class embeddings in Redis → if best match >= threshold (e.g. 0.75), assert `(individual, rdf:type, BestClass)`
- Phase 2 — LLM fallback: for individuals below threshold, batch-send with list of known classes → LLM picks most appropriate or returns `null`
- Tag all inferred type assertions as `source: "pipeline_inferred"` (see §1)

---

## Recommended Implementation Order

1. **Provenance metadata** — low effort, unlocks chain-delete and audit capabilities
2. **Individual labeling** — fills semantic gaps, mostly embedding-based so fast
3. **Pruning** — last, requires threshold tuning; run in log-only mode first

## Pipeline Order (after all three implemented)

```
extraction
    ↓
pruning                 ← score + filter low-confidence triplets
    ↓
entity_classification
    ↓
entity_linking
    ↓
individual_labeling     ← assign rdf:type to untyped individuals
    ↓
schema_mapping
    ↓
ontology_construction   ← emits kg:source annotation on all entities
    ↓
reasoning
    ↓
validation
    ↓
turtle_serialization
```
