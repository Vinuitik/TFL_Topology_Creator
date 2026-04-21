# Claude Session Notes

## User Preference
**Be truly laconic.** Short, direct answers only. No TLDR walls of text.
**Workflow:** Diagnose → Plan → (joint refinement) → user approval → Execute.

## Project: KG2 — Knowledge Graph Pipeline

### What it does
Extracts a knowledge graph (OWL/Turtle) from unstructured `.txt` files via a LangGraph pipeline.

### Stack
- **LangGraph** state machine (`llm_pipeline/agent.py`)
- **REBEL** (`Babelscape/rebel-large`) for triplet extraction — runs locally via HuggingFace
- **Ollama** via HTTP — two models:
  - `gemma2:2b` — main LLM (schema mapping, ontology construction, reasoning, validation)
  - `qwen2.5:1.5b` — lightweight entity model (entity linking, entity classification)
  - `nomic-embed-text` — embeddings for entity linking
- **spacy-experimental** (`en_coreference_web_trf`) — transformer-based coreference resolution, no LLM
- **Redis** — entity linking cache (descriptions + embeddings keyed `entities:desc:{name}` etc.)
- **rdflib** — final OWL/Turtle serialization
- **Docker Compose** — services: `llm-pipeline`, `ollama`, `redis`

### Pipeline stages (in order)
1. `input_ingestion` — load raw text into Document
2. `text_normalization` — clean/normalise text
3. `coreference_resolution` — spacy-experimental coref chains, longest-span canonical, char substitution
4. `extraction` — REBEL seq2seq → raw triplets
5. `entity_linking` — deduplicate entity/relation surface forms via DSU + embedding cosine + LLM batch comparison; canonical names persisted to Redis
6. `entity_classification` — classify each entity as `class`/`individual`, each relation as `object_property`/`datatype_property`; generate `rdfs:label` + `rdfs:comment` for all; stored in `entity_catalog`
7. `schema_mapping` — map entities/relations to OWL IRIs; classes get their own IRI, individuals get `/entity/` IRI; predicate kind propagated
8. `ontology_construction` — emit OWL triples: `owl:Class`, `owl:NamedIndividual`, `owl:ObjectProperty`/`owl:DatatypeProperty` with labels + comments
9. `reasoning` — LLM infers additional triples
10. `validation` — LLM validates; can loop back (max 2 iterations) to `coreference_resolution`, `extraction`, `entity_linking`, or `schema_mapping`
11. `turtle_serialization` — rdflib serialises to OWL/Turtle

**Commented-out stages** (preserved, can be re-enabled):
- `preprocessing` — LLM paraphrase to Wikipedia prose (too slow for large sources)

### Models summary
| Model | Purpose | Env var |
|---|---|---|
| `qwen2.5:7b` | all LLM calls — entity linking, classification, coreference, schema mapping | `OLLAMA_ENTITY_MODEL` |
| `mxbai-embed-large` | embeddings for entity similarity (1024-dim) | `OLLAMA_EMBED_MODEL` |
| `en_coreference_web_trf` | coreference resolution | baked into Docker image |
| `Babelscape/rebel-large` | triplet extraction | HuggingFace, cached in `HF_HOME` |

### Chunking
Large inputs (>`CHUNK_MAX_WORDS`, default 600) are split on sentence boundaries (`(?<=[.!?])\s+(?=[A-Z])`).
- **preprocessing**: chunks processed independently, outputs concatenated
- **coreference**: last 2 sentences of previous chunk prepended as `[CONTEXT]` to preserve cross-boundary resolution

### Caching & timing
- **File hash cache**: SHA-256 of each source file stored in `outputs/file_hashes.json`; unchanged files skip the full pipeline and reuse saved run JSON
- **Per-stage timing**: every LangGraph node wrapped with `@timed_node`; elapsed times in `run_summary.json` under `per_stage_timings` (per file) and `cumulative_timings` (across all files)

### Entry points
- `run_pipeline.ps1` — Docker full run: starts services, pulls models, ingests OWL/TTL, runs pipeline on `data_sources/Unstructured-*.txt`
- `run_tests.ps1` — pytest against `.venv` locally
- `llm_pipeline/agent.py` — batch runner; writes `outputs/final.owl`, `final.ttl`, `run_summary.json`
- `llm_pipeline/ingest_owl.py` — seeds Redis + `rag_catalog.json` from `inputs/*.owl|ttl|rdf` before pipeline runs

### OWL inputs
Place `.owl`, `.ttl`, or `.rdf` files in `inputs/` — they are parsed at pipeline start by `ingest_owl.py`, entities/properties embedded and written to Redis, merged into `outputs/rag_catalog.json` for downstream use.

### Outputs
- `outputs/runs/{idx}_{stem}.json` — per-file full pipeline state
- `outputs/final.owl` / `outputs/final.ttl` — merged knowledge graph across all sources
- `outputs/run_summary.json` — timestamps, triple counts, timings, cache hits
- `outputs/rag_catalog.json` — accumulated class/predicate IRI catalog
- `outputs/file_hashes.json` — SHA-256 cache index

### Test state (as of 2026-04-19)
- `llm_pipeline/tests/test_pipeline.py` — 20 unit tests, all passing
- Tests are **pure/offline only** (no network, no model calls, no Redis)

### Current branch
`reasoning-ontology-pipeline-v2`
