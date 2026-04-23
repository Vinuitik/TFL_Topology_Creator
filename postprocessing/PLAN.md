# KG2 Post-Processing Plan

## Goal

Clean and deduplicate `outputs/final.ttl` → `outputs/final_clean.ttl` without re-running
extraction. The SPARQL queries in `Ontology/Sparql_queries.txt` must return meaningful
results against the cleaned output.

## Inputs

| File | Role |
|---|---|
| `outputs/final.ttl` | Raw pipeline output (~10k lines); contains duplicates and type errors |
| `final_ontology.ttl` | Hand-crafted TfL ontology schema; defines the **protected IRI set** |
| Redis | Embeddings from the construction run stored under `entities_class:emb:*`, `entities_individual:emb:*` |

## Why the construction pipeline left duplicates

- `ENTITY_SAME_THRESHOLD=0.96` was too high — near-identical names like *"Elizabeth Line"*
  and *"ElizabethLine"* were not merged.
- The LLM classifier sometimes emitted a named service (e.g. "Victoria Line") as
  `owl:Class` instead of `owl:NamedIndividual`, because the prompt had no explicit
  instance-vs-concept hint.
- Structured (JSON/TSV) and unstructured (txt) pipelines ran independently and produced
  overlapping IRIs for the same real-world entities.

## Key design invariants

1. **Protected IRIs** — every IRI that appears as a subject in `final_ontology.ttl` is
   anchored. It is **never aliased away, renamed, or demoted**. Protected classes keep
   their class typing; protected individuals keep their individual typing.
2. **Separate type buckets** — classes are only deduped against classes; individuals only
   against individuals. Cross-type resolution is handled explicitly in Phase 3.
3. **New prompt files** — all LLM calls use prompts in `postprocessing/prompts/`. They are
   never loaded from `llm_pipeline/prompts/`. This preserves reproducibility of the
   construction pipeline.
4. **No Redis flush** — embeddings from the construction run are reused. Missing embeddings
   are generated on demand via Ollama.

## Threshold variables (`.env`)

| Variable | Construction value | Post-processing value | Effect |
|---|---|---|---|
| `ENTITY_SAME_THRESHOLD` | 0.96 | — | Used only by the construction pipeline |
| `POST_ENTITY_SAME_THRESHOLD` | — | 0.75 | Cosine similarity gate for merging (more aggressive) |
| `POST_FUZZY_THRESHOLD` | — | 88 | Token-sort-ratio gate (0–100) for candidate pairs |

---

## Phase 0 — Load & Anchor

**Script section:** `load_protected()`, graph parse

1. Parse `final_ontology.ttl` with rdflib.
2. Collect every subject URI → `protected_iris: Set[URIRef]`.
3. Record the declared `rdf:type` for each protected IRI → `protected_types: Dict[URIRef, Set[URIRef]]`.
   - Used in Phase 1 to resolve type collisions without an LLM call.
4. Parse `outputs/final.ttl` into the working graph `g`.
5. Log initial stats: triple count, class count, individual count.

**Why separately:** The protected set must be frozen before any mutation. Loading it first
ensures no phase can accidentally demote or alias a protected IRI.

---

## Phase 1 — Class/Individual Collision Resolution

**Script section:** `phase1_resolve_collisions()`

**Problem:** The pipeline occasionally emits the same IRI with `rdf:type owl:Class` AND
`rdf:type owl:NamedIndividual`. This is structurally invalid OWL and confuses SPARQL
`rdf:type/rdfs:subClassOf*` path queries.

**Algorithm:**

```
collisions = {IRIs typed as both owl:Class AND owl:NamedIndividual}

for each IRI in collisions:
    if IRI in protected_iris:
        keep the type declared in final_ontology.ttl (trusted ground truth)
        remove the other typing
    else:
        call LLM post_type_judge(label)
        if result == "class"  → remove owl:NamedIndividual typing
        if result == "individual" → remove owl:Class typing
```

**Output:** Working graph with no collision IRIs. Count of resolutions logged.

**Prompt used:** `post_type_judge-v1.txt`
- Input: entity label + generic description
- Output: `{"type": "class"}` or `{"type": "individual"}`
- Key hint in prompt: named transport services/stations are always individuals; generic
  categories (Station, Line, Route) are always classes.

---

## Phase 2 — Within-Type Deduplication

**Script section:** `phase2_dedup_type()` — called twice (classes, then individuals)

**Problem:** Multiple IRIs represent the same real-world entity within the same type.
Example: `local:ElizabethLine`, `local:elizabeth_line_0`, `local:ElizabethLine_1` are all
`owl:NamedIndividual` referring to the Elizabeth Line service.

**Algorithm (per type bucket):**

```
Step 1 — Fuzzy candidate pairs
  For every pair (IRI_a, IRI_b) in the bucket:
    score = token_sort_ratio(label_a, label_b)   # 0–100, stdlib difflib
    if score >= POST_FUZZY_THRESHOLD (88): add to candidates

Step 2 — Embedding cosine filter
  Fetch embeddings from Redis:
    keys tried: "{category}:emb:{label}", "entities:emb:{label}"
  If missing: generate via Ollama mxbai-embed-large, store result
  For each candidate pair:
    if cosine(emb_a, emb_b) >= POST_ENTITY_SAME_THRESHOLD (0.75): → merge_pair

Step 3 — DSU clustering
  Build DSU over all IRIs in bucket
  union(a, b) for each merge_pair

Step 4 — LLM cluster judge
  For each cluster with 2+ members:
    call LLM post_dedup_judge(type_label, member_labels)
    if LLM says {"same": false}: skip (no merge for this cluster)
    if LLM says {"same": true}:
      canonical = protected IRI in cluster  (if any)
               OR IRI with highest graph degree (most triples)
      alias_map[alias] = canonical  for all non-canonical members
```

**Output:** `alias_map: Dict[URIRef, URIRef]` — one map per type. Merged separately then
combined before rewriting.

**Prompt used:** `post_dedup_judge-v1.txt`
- Different from `entity_linking-v4.txt`: explicitly states named services are instances,
  not classes. Warns against merging different named services together.
- More conservative on class merges; more permissive on spelling variants of the same
  individual.

**Redis category keys:**
- Classes → `entities_class:emb:{label}`
- Individuals → `entities_individual:emb:{label}`

---

## Phase 3 — Cross-Type Resolution (Demote Spurious Classes)

**Script section:** `phase3_cross_type()`

**Problem:** The pipeline sometimes emits a named entity (e.g. "Elizabeth Line") as an
`owl:Class` AND separately as an `owl:NamedIndividual` under different IRIs. Phase 2
doesn't catch this because it operates within a single type bucket.

**Algorithm:**

```
class_iris   = [non-protected classes with labels]
ind_iris     = [individuals with labels]

for each (cls_iri, cls_label) in class_iris:
    for each (ind_iri, ind_label) in ind_iris:
        score = token_sort_ratio(cls_label, ind_label)
        if score < POST_FUZZY_THRESHOLD: continue

        call LLM post_type_judge(cls_label)
        if result == "individual":
            alias_map[cls_iri] = ind_iri   # redirect class IRI → individual IRI
            remove (cls_iri, rdf:type, owl:Class) from graph
            log demotion
            break   # one match per class is enough
```

**Why not merge both IRIs by default:** If the class IRI appears in domain/range axioms
(unlikely for LLM-generated spurious classes), aliasing it to an individual would corrupt
those axioms. We remove only the class typing and let Phase 4 (rewriting) propagate the
merge.

**Output:** Mutated graph (class typing removed) + `alias_cross: Dict[URIRef, URIRef]`.

---

## Phase 4 — Canonical Rewriting

**Script section:** `rewrite_graph()`

Combines `alias_cls + alias_ind + alias_cross` into one `alias_map`.

```
new_g = empty Graph
copy namespace bindings from g

for each (s, p, o) in g:
    s' = alias_map.get(s, s)
    p' = alias_map.get(p, p)
    o' = alias_map.get(o, o)  if o is URIRef
    new_g.add((s', p', o'))
```

**Effect:** All triples referencing alias IRIs now point to the canonical IRI. Old alias IRI
entries are implicitly removed (they appear nowhere as subject/predicate/object). The graph
shrinks in triple count.

---

## Phase 5 — Type Assertion Repair

**Script section:** `phase5_repair_types()`

**Problem:** After deduplication and rewriting, some `owl:NamedIndividual` entries have no
`rdf:type` triple beyond `owl:NamedIndividual`. SPARQL queries like
`?station a :InterchangeStation` will return nothing for them.

**Algorithm:**

```
class_index = {label.lower(): IRI  for each owl:Class in g}

for each owl:NamedIndividual ind in g:
    meaningful_types = {types of ind} - {owl:NamedIndividual}
    if meaningful_types: skip  (already typed)

    ind_label = rdfs:label of ind (or CamelCase-split local name)
    best_class = class whose label is the longest substring of ind_label
    if best_class found:
        g.add((ind, rdf:type, best_class))
```

**Examples:**
- `"Victoria Line"` individual → matches class label `"Line"` → typed as `local:Line`
- `"Oxford Circus Station"` → matches `"Station"` → typed as `local:Station`
- `"Zone 1"` → matches `"Zone"` → typed as `local:Zone`
- `"Step-Free Access"` → matches `"Accessibility Feature"` → typed as `local:AccessibilityFeature`

**Why longest match:** Prevents `"Train Station"` from matching `"Station"` when
`"Train Station"` is available as a class label.

---

## Phase 6 — Reasoning

**Script section:** `phase6_reasoning()`

Adds inferred triples without re-running the full REBEL/LLM pipeline.

**Rules applied:**

1. **Inverse properties:** For each `owl:ObjectProperty` with `owl:inverseOf`:
   ```
   (s, prop, o) → (o, inverse_prop, s)
   ```
2. **Symmetric properties:** For each `owl:SymmetricProperty`:
   ```
   (s, prop, o) → (o, prop, s)
   ```
   Applies to `local:directlyConnectedTo` (declared symmetric in final_ontology.ttl).
3. **One-step subClassOf type propagation:** For each individual typed as class C where
   `C rdfs:subClassOf D`:
   ```
   (ind, rdf:type, C) → (ind, rdf:type, D)
   ```
   Example: individual typed as `local:InterchangeStation` → also typed as `local:TrainStation`
   → also `local:Station` → also `local:TransitAccessPoint`.

**Why one-step only:** Full transitive closure via `rdfs:subClassOf*` is handled by SPARQL
query engines natively (the queries use `rdf:type/rdfs:subClassOf*`). Adding one level of
explicit assertions is enough to support queries that use `a :ClassName` without the path.

---

## Phase 7 — Serialize

Serialize the cleaned graph to `outputs/final_clean.ttl` in Turtle format via rdflib.
Log final stats: triple count, class count, individual count, delta from initial.

---

## Acceptance criteria

Run each query in `Ontology/Sparql_queries.txt` against `final_clean.ttl`.

| Query | What it needs |
|---|---|
| Q1 | `local:hasStop`, `local:hasName`, `local:hasZone`, `local:zoneNumber` populated for Victoria Line stations |
| Q2 | Station individuals typed as `local:InterchangeStation` where applicable |
| Q3 | `local:RouteStopSequence` individuals with `local:stopSequenceNumber`, `local:sequenceStop`, `local:belongsToRoute` |
| Q4 | Adjacent stop pairs via `local:RouteStopSequence` with sequence numbers |
| Q5 | Stations with `local:hasStop` from 2+ lines |
| Q7 | Stations with `local:hasZone` → Zone individual with `local:zoneNumber` = 1 |

---

## File map

```
postprocessing/
  PLAN.md                          ← this file
  post_process.py                  ← standalone Python script (no imports from llm_pipeline/)
  prompts/
    post_dedup_judge-v1.txt        ← within-type dedup LLM judge
    post_type_judge-v1.txt         ← class-vs-individual disambiguation

post_processing.ps1                ← Windows runner (no Redis flush)
post_processing.sh                 ← Linux/Kishan runner (no Redis flush)
```

## Running

```powershell
# Windows
./post_processing.ps1

# Linux
bash post_processing.sh
```

Output: `outputs/final_clean.ttl`
