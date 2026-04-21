# LLM Pipeline

Turns unstructured `.txt` files (or JSON/TTL data sources) into an OWL/Turtle knowledge graph via a LangGraph state machine.

---

## Services

| Service | Role |
|---|---|
| `ollama` (Docker) | Runs `qwen2.5:7b` locally. Used for coreference resolution, entity description generation, entity comparison, canonical name selection, and entity classification. Must bind on `0.0.0.0:11434` — set via `OLLAMA_HOST=0.0.0.0:11434` in docker-compose. |
| `redis` (Docker) | Caches entity descriptions and embedding vectors between pipeline states. Keys: `entities:desc:{name}`, `entities:emb:{name}`, `relations:desc:{name}`, `relations:emb:{name}`, `*:canonical:{name}`. |
| REBEL (`Babelscape/rebel-large`) | HuggingFace seq2seq model loaded inside the `llm-pipeline` container. Runs entirely locally — no network call. Extracts `(subject, predicate, object)` triplets from sentences. |

---

## How to Run

```powershell
.\run_pipeline.ps1
```

Steps executed:
1. Start Redis + Ollama (`docker compose up -d`)
2. Pull `gemma4:e4b` if not already cached
3. **Ingest** any `.owl`/`.ttl`/`.rdf` files from `inputs/` → seeds Redis + `rag_catalog.json`
4. Run `agent.py` over all `Unstructured-*.txt` files in `data_sources/`
5. Write `outputs/final.owl`, `outputs/final.ttl`, `outputs/run_summary.json`

Drop OWL/TTL files into `inputs/` before running to pre-seed entity knowledge. If `inputs/` is empty the ingest step is skipped silently.

---

## Pipeline Graph

```
input_ingestion
      ↓
preprocessing          ← LLM rewrites input into Wikipedia-style prose
      ↓
text_normalization     ← regex clean + sentence split + tokenize
      ↓
coreference_resolution ← LLM replaces pronouns with named entities
      ↓
extraction             ← REBEL extracts (subject, predicate, object) triplets
      ↓
entity_linking         ← Redis cache + Ollama embeddings + LLM deduplication
      ↓
schema_mapping         ← matches entities/predicates against rag_catalog + defaults
      ↓
ontology_construction  ← assigns OWL IRIs, declares owl:Class + owl:NamedIndividual
      ↓
reasoning              ← adds inferred triples (inverses, symmetry, ConnectedEntity type)
      ↓
validation             ← checks IRI validity, relation presence, linking conflicts
      ↓ (conditional)
  ┌── end → turtle_serialization → Turtle + OWL/XML strings in state
  │
  └── loop back (max 2 iterations) to:
        entity_linking   if linking conflicts
        extraction       if no relations found
        coreference_resolution  if low confidence
```

---

## State Details

### `preprocessing`
Sends the full raw text to Ollama with few-shot examples and asks it to rewrite into clean declarative sentences. Handles legal prose, JSON API dumps, and informal text. Replaces `document.raw_text` in state; downstream states see only the rewritten version.

### `text_normalization`
Regex-only. Collapses whitespace, splits on `.!?` boundaries, tokenises with `\b\w+\b`.

### `coreference_resolution`
Ollama LLM call. Prompt: `coreference_resolution-v*.txt`. Returns `{"resolved_text": "..."}`. Falls back to passing text through unchanged if LLM is unavailable.

### `extraction`
REBEL (`Babelscape/rebel-large`) runs on each sentence from the resolved document. Output format: `<triplet> subject <subj> object <obj> predicate`. Each triplet stores the source sentence as `provenance_sentence`.

### `entity_linking`
Three-phase process per run, operating on all subjects, objects, and predicates from the extracted triplets:

1. **Describe** — generates a 15–25 word description per entity via Ollama (`entity_linking_describe` prompt). Writes to Redis `entities:desc:{name}`.
2. **Embed** — POSTs description to Ollama `/api/embeddings` with `gemma4:e4b`. Writes JSON vector to Redis `entities:emb:{name}`.
3. **Cluster** — builds candidate pairs via token-Jaccard + cosine similarity, then sends batches of 20 pairs to Ollama (`entity_linking` prompt) to decide if they are the same entity. Uses DSU (union-find) to cluster matches, then picks a canonical name per cluster (`entity_linking_canonical` prompt). Rewrites all triplets to use canonical names.

### `schema_mapping`
Loads `rag_catalog.json` (accumulated across runs) and merges it with a hardcoded default catalog (transport-domain classes and predicates). Uses `difflib.SequenceMatcher` to match each entity label and predicate to the best catalog entry (threshold 0.6 for classes, 0.66 for predicates). Assigns IRIs under `http://example.org/pt#`. Unmatched predicates are flagged.

### `ontology_construction`
Converts the mapped graph into a flat list of triple dicts (`subject`, `predicate`, `object`, `is_literal`, `datatype`). Declares each unique class as `owl:Class`, each entity as `owl:NamedIndividual`, and stores provenance sentences via `prov:value`.

### `reasoning`
Pure Python, no LLM. Adds:
- `rdf:type pt:ConnectedEntity` for every node that appears in any non-type relation
- Inverse triples for `pt:operates` ↔ `pt:operatedBy`
- Symmetric triples for `pt:relatedTo`

### `validation`
Checks: at least one triple exists, at least one non-type relation exists, all subjects and predicates are valid IRIs, no linking conflicts. Sets `reroute_target` and `failed_validation` flags for the feedback router.

### `turtle_serialization`
Uses `rdflib` to build a Graph from the validated triple dicts and serialises to both Turtle and OWL/XML strings stored in state. The batch runner (`agent.py`) then writes these to `outputs/final.ttl` and `outputs/final.owl`.

---

## RAG Catalog

`outputs/rag_catalog.json` accumulates `{label, iri}` entries for classes and predicates across runs. It is:
- **Written to** by `ingest_owl.py` (from `inputs/` OWL/TTL files) and by `agent.py` (from each processed file)
- **Read from** by `schema_mapping` to improve IRI assignment accuracy over time

---

## Prompts

All prompts live in `prompts/` and follow the naming convention `{state_name}-v{N}.txt`. The LLM service auto-selects the highest version. Prompts are prepended to the input text before being sent to Ollama.

| Prompt | Used by |
|---|---|
| `preprocessing-v1.txt` | preprocessing state |
| `coreference_resolution-v2.txt` | coreference_resolution state |
| `entity_linking_describe-v1.txt` | entity_linking (description step) + ingest_owl |
| `entity_linking-v1.txt` | entity_linking (comparison step) |
| `entity_linking_canonical-v1.txt` | entity_linking (canonical name step) |

---

## Key Environment Variables (docker-compose)

| Variable | Default | Used by |
|---|---|---|
| `OLLAMA_ENTITY_MODEL` | `qwen2.5:3b` | all LLM generate calls |
| `OLLAMA_EMBED_MODEL` | `mxbai-embed-large` | embedding calls in entity_linking + ingest_owl |
| `OLLAMA_TIMEOUT_SEC` | `45` | per-request HTTP timeout |
| `OLLAMA_HOST` | `0.0.0.0:11434` | Ollama bind address (must be 0.0.0.0 for inter-container access) |
| `REDIS_URL` | `redis://redis:6379` | entity cache |
