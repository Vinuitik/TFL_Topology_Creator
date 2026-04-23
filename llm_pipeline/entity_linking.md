# Entity Linking Pipeline

## Scope

Three categories processed identically: `entities`, `relations`, `individuals`.

---

## Steps

### 1. Description Generation
For each item missing a description:
- Input: item name only
- LLM generates a description: 15–25 words
- *(Future: regex-extract name occurrences from source text for richer context before generation)*

### 2. Embedding
For each item missing an embedding:
- Embed the description
- Persist to Redis keyed by item name

### 3. Pairwise LLM Comparison — O(n²/2) per category
For each pair (A, B):
- Send both names + descriptions to LLM (CoT model)
- LLM judges: same real-world concept or not
- Output: `{"same": true}` or `{"same": false}`

No cosine similarity threshold — LLM is the sole judge.

### 4. Clustering via DSU
- "Same" pairs form edges in a graph
- Run Disjoint Set Union → clusters of equivalent items

### 5. Canonical Naming
For each cluster (including size-1):
- Collect all names in the cluster
- LLM prompt → single compressed canonical name
- Example: `"located in the administrative territorial entity"` → `"located in"`

### 6. Persist
- Descriptions, embeddings, canonical names written back to Redis
- Future runs skip generation/embedding for already-known items

---

## Storage

Redis — plain key-value sufficient since full pairwise comparison is performed (no ANN search required). Redis Stack only needed if O(n²/2) becomes a bottleneck and approximate nearest-neighbour pre-filtering is introduced.
