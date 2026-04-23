# llm_pipeline

LangGraph state machine that turns unstructured `.txt` files into an OWL/Turtle knowledge graph.

See the root [README.md](../README.md) for full architecture, configuration, and run instructions.

---

## Stage Reference

### `extraction`
Three triplet sources merged and deduplicated:
1. **REBEL** (`Babelscape/rebel-large`) — batched GPU inference (`REBEL_BATCH_SIZE=4`). Before loading, both Ollama models are evicted from VRAM; after, GPU memory is freed via `gc.collect()` → `empty_cache()` → `ipc_collect()`.
2. **spaCy NER** (`en_core_web_lg`) — emits `(entity, type, ClassName)` triplets for ORG/GPE/LOC/FAC/LAW/PRODUCT/EVENT spans.
3. **LLM extraction** — chunked text sent to Ollama; output merged with REBEL triplets.

### `entity_classification`
- Classifies each unique entity/predicate as `class`, `individual`, `object_property`, or `datatype_property`
- Descriptions generated in batches of `CLASSIFY_BATCH_SIZE` per LLM call
- Embeddings fetched in parallel via `ThreadPoolExecutor(EMBED_WORKERS)` with retry on Docker DNS failure
- KNN (`CLASSIFY_KNN_K` neighbours) against Redis-cached embeddings assists classification

### `entity_linking`
- DSU (union-find) clusters candidates whose cosine similarity ≥ `ENTITY_SAME_THRESHOLD`
- Each cluster gets **one** LLM call (O(N), not O(N²)) to confirm or disband
- LLM prompt is type-aware: merger rules differ for `class` vs `individual` vs properties
- Canonical names written to Redis (`{kind}:canonical:{name}`)
- Original ontology names are protected — `ingest_owl.py` pre-writes canonical keys that linking never overwrites

### `schema_mapping`
- Fuzzy-matches entities/predicates to `rag_catalog.json` + hardcoded transport defaults
- `ALLOW_NEW_ENTITIES=false` (default): new classes not in the catalog are demoted to individuals, preserving their literal-valued datatype assertions
- Literals (`xsd:integer`, `xsd:decimal`) bypass entity lookup and attach directly to their subject individual

### `ontology_construction`
Emits flat triple dicts; declares `owl:Class`, `owl:NamedIndividual`, `owl:ObjectProperty`, `owl:DatatypeProperty` with `rdfs:label` + `rdfs:comment`.

### `reasoning`
Pure Python. Adds inverse triples (`pt:operates` ↔ `pt:operatedBy`), symmetric triples (`pt:relatedTo`), and `rdf:type pt:ConnectedEntity` for nodes appearing in non-type relations.

### `validation`
Checks IRI validity, triple presence, relation presence. Sets `reroute_target` for the LangGraph feedback router; max 2 loop-back iterations.

### `turtle_serialization`
rdflib builds a Graph from validated triples and serialises to Turtle + OWL/XML.

---

## LLM Service (`service/llm.py`)

- `call_llm(state_name, params, model, extra_options, timeout)`
- Auto-selects highest prompt version from `prompts/{state_name}-v*.txt`
- `stream=True` — partial response parsed on timeout (no data loss)
- Retries on bad JSON only, up to `OLLAMA_MAX_RETRIES`; seed increments per attempt (`OLLAMA_SEED + attempt - 1`)

## Prompts (`prompts/`)

| File | Used by |
|---|---|
| `extraction-v*.txt` | LLM extraction in extraction state |
| `entity_describe_batch-v*.txt` | Batch describe in entity_classification + entity_linking |
| `entity_linking-v*.txt` | O(N) cluster judge in entity_linking |
| `entity_classification-v*.txt` | Kind classification |
| `coreference_resolution-v*.txt` | Coreference state |
| `entity_linking_describe-v*.txt` | Single-entity describe in ingest_owl |

All prompts: highest version number wins.
