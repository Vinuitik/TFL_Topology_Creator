# Claude Session Notes

## User Preference
**Be truly laconic.** Short, direct answers only. No TLDR walls of text.
**Workflow:** Diagnose → Plan → (joint refinement) → user approval → Execute.

## Project: KG2 — Knowledge Graph Pipeline

### What it does
Extracts a knowledge graph (OWL/Turtle) from both unstructured `.txt` files and structured TfL API JSON/TSV files via a LangGraph pipeline. Pipeline has been successfully run end-to-end; `outputs/final.ttl` (~10k lines) and `outputs/final.owl` exist. Reasoner completed without errors.

### Stack
- **LangGraph** state machine (`llm_pipeline/agent.py`)
- **REBEL** (`Babelscape/rebel-large`) — batched GPU triplet extraction (HuggingFace)
- **Ollama** via HTTP:
  - `qwen2.5:3b` (`OLLAMA_ENTITY_MODEL`) — all LLM calls (entity linking, classification, schema mapping, reasoning, validation)
  - `mxbai-embed-large` (`OLLAMA_EMBED_MODEL`) — 1024-dim embeddings
- **spacy-experimental** (`en_coreference_web_trf`) — transformer coreference resolution, no LLM
- **spaCy** (`en_core_web_lg`) — NER for type-assertion triplets
- **Redis** — entity cache: `{category}:desc:{name}`, `{category}:emb:{name}`, `{kind}:canonical:{name}`
- **rdflib** — OWL/Turtle serialization
- **Docker Compose** — services: `llm-pipeline`, `ollama`, `redis`

### Pipeline stages (in order)
1. `input_ingestion` — load raw text into Document
2. `text_normalization` — clean/normalise text
3. `coreference_resolution` — spacy-experimental coref; longest-span canonical; char substitution
4. `extraction` — REBEL (batched, GPU) + spaCy NER + LLM extraction → raw triplets
5. `entity_classification` — batch LLM classify (class/individual/object_property/datatype_property); batch describe + parallel embed; KNN-assisted; stores `entity_catalog`
6. `entity_linking` — DSU + cosine similarity threshold + O(N) type-aware LLM cluster judge; canonical names written to Redis
7. `schema_mapping` — IRI assignment; ALLOW_NEW_ENTITIES demotes new classes to individuals
8. `ontology_construction` — emit `owl:Class`, `owl:NamedIndividual`, `owl:ObjectProperty`/`owl:DatatypeProperty` with labels + comments
9. `reasoning` — infers additional triples (inverses, symmetry, type assertions)
10. `validation` — structural checks; loops back (max 2 iterations) to extraction/linking/schema_mapping
11. `turtle_serialization` — rdflib → OWL/Turtle

**Commented-out stages** (preserved, re-enable in agent.py):
- `preprocessing` — LLM paraphrase to Wikipedia prose (too slow for large sources)

### Models summary
| Model | Purpose | Env var |
|---|---|---|
| `qwen2.5:3b` | all LLM generate calls | `OLLAMA_ENTITY_MODEL` |
| `mxbai-embed-large` | embeddings (1024-dim) | `OLLAMA_EMBED_MODEL` |
| `en_coreference_web_trf` | coreference resolution | baked into Docker image |
| `Babelscape/rebel-large` | triplet extraction | HuggingFace, cached in `HF_HOME` |
| `en_core_web_lg` | NER type assertions | loaded in extraction state |

### Key design features

**VRAM orchestration:** Before loading REBEL, both Ollama models are evicted (`keep_alive=0`). After REBEL: `gc.collect()` → `torch.cuda.empty_cache()` → `torch.cuda.ipc_collect()`. spaCy unloaded in `finally` block.

**REBEL batching:** `REBEL_BATCH_SIZE` sentences per GPU call (default 4) with `padding=True`. Amortizes beam search overhead.

**O(N) cluster judge:** DSU clusters by cosine similarity; one LLM call per cluster to confirm/disband. Type-aware prompt (class/individual/object_property/datatype_property).

**Batch describe + parallel embed:** `CLASSIFY_BATCH_SIZE` entities per LLM call; embeddings fetched via `ThreadPoolExecutor(EMBED_WORKERS)` with 3-attempt retry on DNS failure.

**Streaming LLM + partial parse:** `stream=True`; on timeout, partial accumulated response is parsed. Retries only on bad JSON; seed increments per attempt (`OLLAMA_SEED + attempt - 1`).

**Ontology-anchored canonical names:** `ingest_owl.py` writes `{kind}:canonical:{label}` for every OWL entity. Entity linking checks these before any rename — original ontology names are never overwritten.

**ALLOW_NEW_ENTITIES=false (default):** New classes not in `rag_catalog` are demoted to individuals (not dropped) — preserves their literal-valued datatype property assertions.

**SHA-256 file hash cache:** Unchanged source files skip the full pipeline. Hash + Redis spot-check both required for cache hit.

### Chunking
Large inputs (`> CHUNK_MAX_WORDS`, default 600) are split on sentence boundaries. Coreference: last 2 sentences of previous chunk prepended as `[CONTEXT]`.

### Caching & timing
- **File hash cache**: SHA-256 stored in `outputs/file_hashes.json`; Redis spot-check guards against flush
- **Per-stage timing**: every LangGraph node wrapped with `@timed_node`; elapsed in `run_summary.json`

### Entry points
- `run_pipeline.ps1` — Docker full run (Windows)
- `run_pipeline_gpu.sh` — Docker full run (Linux/Kishan's setup); GPU-aware, flushes Redis, `--build` on both compose run calls
- `run_eval.ps1` — SPARQL tool-use eval against `outputs/final.ttl`
- `llm_pipeline/agent.py` — batch runner
- `llm_pipeline/ingest_owl.py` — seeds Redis + `rag_catalog.json` from `inputs/*.owl|ttl|rdf`

### OWL inputs
Drop `.owl`, `.ttl`, `.rdf` into `inputs/` — parsed by `ingest_owl.py`, entities embedded, written to Redis, merged into `rag_catalog.json`. Their `kind` field drives the canonical key namespace.

### Outputs
- `outputs/runs/{stem}.json` — per-file full pipeline state (no idx prefix; cache-robust)
- `outputs/final.owl` / `outputs/final.ttl` — merged knowledge graph
- `outputs/run_summary.json` — timestamps, triple counts, timings, cache hits
- `outputs/rag_catalog.json` — accumulated class/predicate IRI catalog
- `outputs/file_hashes.json` — SHA-256 cache index
- `outputs/eval_results.json` — SPARQL eval results

### Redis cache restore (added 2026-04-23)
On startup, `run_pipeline*.sh/ps1` flushes Redis then runs `ingest_owl.py`. For each cached file (hash hit), `agent.py` calls `_restore_redis_from_cache()` before processing the next file — writes back `{category}:canonical:*`, `{category}:annotation:*`, `{category}:desc:*` from the saved `entity_catalog` in the run JSON. This preserves cross-file entity linking quality without storing embeddings (regenerated on demand).

### Structured pipeline (Kishan's, merged in)
`structured_ingestion` — reads TfL API JSON/TSV, deterministically converts to triplets (camelCase keys → predicate labels, name/id fields → subjects). Skips input_ingestion → coreference → REBEL entirely. Joins shared pipeline at entity_classification. Activated by pattern `*.json` in agent.py args.

### Known bugs fixed
- `UnicodeEncodeError '\udce7'` — lone surrogates from LLM output crashing Redis writes and LangGraph state serialization. Fixed in `agent.py` (input sanitize) and `entity_classification.py` (desc sanitize before Redis SET).

### Test state (as of 2026-04-22)
- `llm_pipeline/tests/test_pipeline.py` — 20 unit tests, all passing
- Tests are **pure/offline only** (no network, no model calls, no Redis)

### Current branch
`reasoning-ontology-pipeline-v2` (merged with `reasoning-ontology-pipeline-kp`)

### Next session goals
**Primary:** Write a post-processing script that deduplicates and cleans the already-generated `outputs/final.ttl` — without re-running extraction (too slow). Goal is to make the SPARQL queries in `Ontology/Sparql_queries.txt` return meaningful results.

**What the script should do (outline, not yet implemented):**
- Load `final.ttl` via rdflib
- Further deduplicate individuals/classes that entity_linking missed (fuzzy string match + embedding cosine on labels)
- Merge duplicate IRIs → pick canonical, rewrite all triples pointing to aliases
- Clean up empty labels, orphaned individuals, broken type assertions
- Re-run reasoning on the cleaned graph
- Serialize back to `outputs/final_clean.ttl`

**Tools available:**
- rdflib (already in requirements) — load, query, mutate, serialize
- Redis (has embeddings from the run) — can reuse for cosine dedup without re-embedding
- `outputs/runs/*.json` — per-file entity_catalog; source of truth for what was classified
- `Ontology/Sparql_queries.txt` — the queries that need to pass; use as acceptance criteria

### final.ttl analysis (TODO next session)
`outputs/final.ttl` is ~10k lines. Useful grep patterns to work through it:
- `grep -c "^<\|^ *<" final.ttl` — count subject blocks
- `grep "rdf:type owl:Class" final.ttl` — all emitted classes
- `grep "rdf:type owl:NamedIndividual" final.ttl` — all individuals
- `grep "rdf:type owl:ObjectProperty\|rdf:type owl:DatatypeProperty" final.ttl` — all properties
- `grep "prov:value" final.ttl | wc -l` — provenance triple count
- `grep -v "^@\|^$\|prov:value\|rdfs:comment" final.ttl | wc -l` — substantive triple estimate
