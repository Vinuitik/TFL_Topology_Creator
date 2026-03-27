# LLM Pipeline Agent

This module exposes a graph-based agent that takes raw text plus metadata and returns a validated ontology-style graph output.

## What You Provide (Input)

The entrypoint is `run_pipeline(raw_text, metadata)` in `agent.py`.

- `raw_text` (string): the source text to process.
- `metadata` (dictionary of strings, optional): source context such as source/date/domain.

Minimal input example:

```python
raw_text = "Tom Cruise starred in Top Gun. He became a global icon in 1986."
metadata = {"source": "demo", "date": "2026-03-20", "domain": "film"}
```

## What It Produces (Output)

The agent returns a pipeline state dictionary that aims to produce:

- extracted triplets (subject, predicate, object) via REBEL, with canonicalized entity spans
- mapped graph representation
- ontology draft and inferred ontology
- validated ontology and validation errors

Main practical outputs to read first:

- `validated_ontology`
- `validation_errors`

## Agent Connection Flow (Graph)

The graph in `agent.py` connects states in this order:

1. input_ingestion
2. text_normalization
3. coreference_resolution
4. extraction
5. entity_linking
6. schema_mapping
7. ontology_construction
8. reasoning
9. validation

After validation, a conditional router decides whether to:

- end the run, or
- loop back to one of:
  - coreference_resolution
  - extraction
  - entity_linking

This feedback loop supports iterative refinement when confidence is low, relations are missing, or validation fails.

## State Intent (Plain English)

1. `input_ingestion`: start with a document and run counter.
2. `text_normalization`: clean text and split it for downstream processing.
3. `coreference_resolution`: replace pronouns with known entities while keeping original spans.
4. `extraction`: run REBEL to extract (subject, predicate, object) triplets covering entities, relations, and attributes in one pass.
5. `entity_linking`: canonicalize entity spans appearing across triplets.
6. `schema_mapping`: place triplets into ontology-aligned buckets. Embeddings or RAG to find current relative schema and change or create new one.
7. `ontology_construction`: convert mapped triplets into triple-like statements.
8. `reasoning`: add inferred facts from existing triples.
9. `validation`: check quality constraints and collect errors.
10. `feedback_router`: decide whether to finish or rerun selected states.

## Scope Note

Internal schemas, extraction logic, and confidence/validation rules are implementation details and may evolve. The stable contract is:

- Input: raw text + optional metadata
- Output goal: validated, ontology-oriented structured result
