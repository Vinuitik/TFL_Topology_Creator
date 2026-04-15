# Claude Session Notes

## User Preference
**Be truly laconic.** Short, direct answers only. No TLDR walls of text.

## Project: KG2 — Knowledge Graph Pipeline

### What it does
Extracts a knowledge graph (OWL/Turtle) from unstructured `.txt` files via a LangGraph pipeline.

### Stack
- **LangGraph** state machine (`llm_pipeline/agent.py`)
- **REBEL** (HuggingFace `Babelscape/rebel-large`) for triplet extraction
- **Ollama** (`gemma4:e4b`) via HTTP for LLM states (coreference, entity linking, schema mapping, ontology, reasoning)
- **Redis** for entity linking cache (descriptions + embeddings)
- **rdflib** for final OWL/Turtle serialization
- Runs via **Docker Compose** (services: `llm-pipeline`, `ollama`, `redis`)

### Pipeline stages (in order)
1. `input_ingestion` → `text_normalization` → `coreference_resolution`
2. `extraction` (REBEL) → `entity_linking` (Redis + Ollama embeddings + LLM)
3. `schema_mapping` → `ontology_construction` → `reasoning` → `validation`
4. Validation can loop back (max 2 iterations) to `entity_linking`, `extraction`, etc.

### Entry points
- `run_pipeline.ps1` — Docker-based full run on `data_sources/Unstructured-*.txt`
- `run_tests.ps1` — runs pytest against `.venv` locally
- `llm_pipeline/run_unstructured.py` — batch runner, writes `outputs/final.owl`, `final.ttl`, `run_summary.json`

### Test state (as of 2026-04-14)
- `llm_pipeline/tests/test_pipeline.py` — 20 unit tests, all passing
- Tests are **pure/offline only** (no network, no model calls, no Redis)
- Old `test_extraction.py` deleted (was stale and model-download-dependent)

### Known issues resolved
- `redis` and `rdflib` were missing from `.venv` — installed
- Ollama model tag `gemma4:e4b` — non-standard, verify it exists in local registry before running Docker pipeline

### Current branch
`reasoning-ontology-pipeline-v2`
