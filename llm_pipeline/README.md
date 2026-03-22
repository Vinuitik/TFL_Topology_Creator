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

- extracted entities (and canonicalized entities)
- extracted relations and attributes
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
4. entity_extraction
5. entity_linking
6. relation_extraction
7. attribute_extraction
8. schema_mapping
9. ontology_construction
10. reasoning
11. validation

After validation, a conditional router decides whether to:

- end the run, or
- loop back to one of:
  - coreference_resolution
  - entity_extraction
  - relation_extraction

This feedback loop supports iterative refinement when confidence is low, relations are missing, or validation fails.

## State Intent (Plain English)

1. `input_ingestion`: start with a document and run counter.
2. `text_normalization`: clean text and split it for downstream processing.
3. `coreference_resolution`: replace pronouns with known entities while keeping original spans.
4. `entity_extraction`: detect entities and assign confidence.
5. `entity_linking`: merge duplicate mentions into canonical entities.
6. `relation_extraction`: create links between entities and flag weak/missing links.
7. `attribute_extraction`: pull datatype-like facts (for example years).
8. `schema_mapping`: place extracted data into ontology-aligned buckets. Embeddings or RAG to find current relative schema and change or create new one.
9. `ontology_construction`: convert mapped data into triple-like statements.
10. `reasoning`: add inferred facts from existing triples.
11. `validation`: check quality constraints and collect errors.
12. `feedback_router`: decide whether to finish or rerun selected states.

## Scope Note

Internal schemas, extraction logic, and confidence/validation rules are implementation details and may evolve. The stable contract is:

- Input: raw text + optional metadata
- Output goal: validated, ontology-oriented structured result
