"""Shared configuration read from environment variables."""
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://ollama:11434/api/embeddings")
OLLAMA_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL", "qwen2.5:3b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.3"))
OLLAMA_SEED = int(os.getenv("OLLAMA_SEED", "42"))
OLLAMA_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC", "3600"))
OLLAMA_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))
EMBED_WORKERS = int(os.getenv("EMBED_WORKERS", "4"))

POST_ENTITY_SAME_THRESHOLD = float(os.getenv("POST_ENTITY_SAME_THRESHOLD", "0.75"))
POST_FUZZY_THRESHOLD = float(os.getenv("POST_FUZZY_THRESHOLD", "88"))
POST_DEDUP_OVERRULE_COSINE = float(os.getenv("POST_DEDUP_OVERRULE_COSINE", "0.88"))
POST_LABEL_LENGTH_STDDEV = float(os.getenv("POST_LABEL_LENGTH_STDDEV", "3.0"))
POST_DOMAIN_FILTER_BATCH = int(os.getenv("POST_DOMAIN_FILTER_BATCH", "20"))
POST_LLM_MODEL = os.getenv("POST_LLM_MODEL", OLLAMA_ENTITY_MODEL)
POST_PROP_LABEL_STDDEV = float(os.getenv("POST_PROP_LABEL_STDDEV", "2.0"))
POST_INFER_COSINE_THRESHOLD = float(os.getenv("POST_INFER_COSINE_THRESHOLD", "0.65"))
POST_INFER_BATCH_SIZE = int(os.getenv("POST_INFER_BATCH_SIZE", "8"))
