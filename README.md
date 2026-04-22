# KG2 — Knowledge Graph Pipeline

Extracts a structured OWL/Turtle knowledge graph from unstructured `.txt` files via a multi-stage LangGraph pipeline. Designed for the public transport domain but configurable for any ontology.

---

## Quick Start

```powershell
.\run_pipeline.ps1
```

1. Starts Redis + Ollama via Docker Compose
2. Pulls the configured LLM and embedding models
3. Ingests any `.owl` / `.ttl` / `.rdf` files from `inputs/` into Redis + `rag_catalog.json`
4. Runs the full pipeline over all `data_sources/Unstructured-*.txt` files
5. Writes `outputs/final.owl`, `outputs/final.ttl`, `outputs/run_summary.json`

```powershell
.\run_tests.ps1   # offline unit tests (no Docker needed)
```

---

## Architecture

### Services

| Service | Role |
|---|---|
| `ollama` | Serves `qwen2.5:3b` (LLM) and `mxbai-embed-large` (embeddings) locally |
| `redis` | Entity cache: descriptions, embedding vectors, canonical name locks |
| `llm-pipeline` | Python container: REBEL, spaCy, LangGraph pipeline |

### Pipeline Stages

```
input_ingestion
      ↓
text_normalization
      ↓
coreference_resolution   ← spacy-experimental (en_coreference_web_trf), no LLM
      ↓
extraction               ← REBEL (batched, GPU) + spaCy NER + LLM extraction
      ↓
entity_classification    ← batch LLM classify + parallel embed
      ↓
entity_linking           ← DSU + cosine similarity + O(N) LLM cluster judge
      ↓
schema_mapping           ← IRI assignment; ALLOW_NEW_ENTITIES guards new schema
      ↓
ontology_construction    ← owl:Class, owl:NamedIndividual, owl:ObjectProperty
      ↓
reasoning                ← inferred triples (inverses, symmetry, type assertions)
      ↓
validation               ← structural checks; loops back up to 2x on failure
      ↓
turtle_serialization     ← rdflib → final.owl + final.ttl
```

---

## Key Design Decisions

### VRAM Orchestration
REBEL (HuggingFace, GPU) and Ollama (also GPU) share the same device. Before loading REBEL, both Ollama models are evicted (`keep_alive=0`). After REBEL finishes, GPU memory is freed in the correct order: `gc.collect()` → `empty_cache()` → `ipc_collect()`. spaCy is unloaded in a `finally` block immediately after NER.

### REBEL Batching
Sentences are grouped into batches of `REBEL_BATCH_SIZE` (default 4) and processed in a single GPU call with `padding=True`. Amortizes beam search overhead across sentences.

### O(N) Cluster Judge
Entity linking uses DSU (union-find) to cluster candidates by cosine similarity. Each resulting cluster gets **one** LLM call to confirm or disband — not one per pair. Scales linearly with the number of clusters, not quadratically with entities.

### Batch Describe + Parallel Embed
Entity descriptions are generated in batches of `CLASSIFY_BATCH_SIZE` per LLM call. Embeddings are fetched in parallel via `ThreadPoolExecutor(EMBED_WORKERS)` with retry on DNS failure.

### Streaming LLM with Partial Parse + Seed-Incrementing Retries
All Ollama calls use `stream=True`. On timeout, the partial accumulated response is parsed rather than discarded — no silent data loss. Retries (up to `OLLAMA_MAX_RETRIES`) only trigger on bad JSON, never on network errors. Each retry increments the seed by 1 (`42 → 43 → 44`): the model stays deterministic within an attempt but explores a different decoding path on the next, avoiding the same malformed output twice.

### Ontology-Anchored Canonical Names
`ingest_owl.py` writes `{kind}:canonical:{label}` keys to Redis for every class, individual, and property extracted from input OWL/TTL files. Entity linking checks these keys before proposing any rename — original ontology names are never overwritten.

### ALLOW_NEW_ENTITIES Flag
When `ALLOW_NEW_ENTITIES=false` (default), entities classified as new classes not present in `rag_catalog` are **demoted to individuals** rather than dropped. Their literal-valued properties (datatype assertions) are preserved; they are typed to the nearest known class via fuzzy match.

### SHA-256 File Hash Cache
Each source file is hashed before processing. Files whose hash matches `outputs/file_hashes.json` **and** whose Redis entries still exist are skipped entirely — no re-embedding, no re-extraction on unchanged inputs.

### Type-Aware Entity Linking
The LLM cluster judge prompt is parameterized by entity type (`class`, `individual`, `object_property`, `datatype_property`). Class merger rules differ from individual distinction rules, preventing inappropriate deduplication across OWL categories.

---

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_ENTITY_MODEL` | `qwen2.5:3b` | LLM for all generate calls |
| `OLLAMA_EMBED_MODEL` | `mxbai-embed-large` | Embedding model |
| `OLLAMA_TIMEOUT_SEC` | `3600` | Per-stream timeout |
| `OLLAMA_TEMPERATURE` | `0.3` | Sampling temperature |
| `OLLAMA_SEED` | `42` | Base seed (incremented per retry) |
| `OLLAMA_MAX_RETRIES` | `3` | Retries on bad JSON only |
| `ALLOW_NEW_ENTITIES` | `false` | Demote new classes to individuals |
| `CHUNK_MAX_WORDS` | `600` | Input chunk size |
| `ENTITY_SAME_THRESHOLD` | `0.96` | Cosine threshold for entity merging |
| `CLASSIFY_BATCH_SIZE` | `8` | Entities per describe LLM call |
| `REBEL_BATCH_SIZE` | `4` | Sentences per REBEL GPU call |
| `EMBED_WORKERS` | `4` | Parallel embed threads |
| `CLASSIFY_KNN_K` | `3` | KNN neighbours for classification |

---

## Outputs

| File | Contents |
|---|---|
| `outputs/final.owl` | Merged OWL/XML knowledge graph |
| `outputs/final.ttl` | Merged Turtle knowledge graph |
| `outputs/run_summary.json` | Timings, triple counts, cache hits |
| `outputs/rag_catalog.json` | Accumulated class + predicate IRI catalog |
| `outputs/file_hashes.json` | SHA-256 cache index |
| `outputs/runs/{idx}_{stem}.json` | Full per-file pipeline state |

---

## OWL Inputs

Drop `.owl`, `.ttl`, or `.rdf` files into `inputs/` before running. `ingest_owl.py` extracts classes, individuals, object properties, and datatype properties; generates descriptions; embeds them; and writes everything to Redis and `rag_catalog.json`. These become the anchor ontology — their names are protected from entity linking rewrites.

---

## Evaluation

```powershell
.\run_eval.ps1
```

Runs a SPARQL tool-use agent against `outputs/final.ttl`. Questions live in `evals/questions.json`; results are written to `outputs/eval_results.json`.
