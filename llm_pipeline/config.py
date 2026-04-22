import os

# Number of parallel requests to send to Ollama.
# If you get Out-Of-Memory errors, lower this to 3 or 2.
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "5"))

# Cosine similarity threshold for merging duplicate entities (0.0 to 1.0)
# Lowering this merges more aggressively (e.g., 0.80 will merge "Station" and "Stations")
ENTITY_SAME_THRESHOLD = float(os.getenv("ENTITY_SAME_THRESHOLD", "0.80"))
