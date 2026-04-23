"""Configuration for completion module."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
COMPLETION_DIR = OUTPUTS_DIR / "completion"

KG_INPUT_PATH = Path(os.getenv("KG_INPUT_PATH", str(OUTPUTS_DIR / "final.ttl")))
KG_OUTPUT_PATH = Path(os.getenv("KG_OUTPUT_PATH", str(OUTPUTS_DIR / "final_completed.ttl")))
ONTOLOGY_PATH = Path(os.getenv("KG_ONTOLOGY_PATH", str(ROOT / "final_ontology.ttl")))
DATA_SOURCES_DIR = Path(os.getenv("KG_SOURCES_PATH", str(ROOT / "data_sources")))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://ollama:11434/api/embeddings")
OLLAMA_ENTITY_MODEL = os.getenv("OLLAMA_ENTITY_MODEL", "qwen2.5:3b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
OLLAMA_TIMEOUT_SEC = float(os.getenv("OLLAMA_TIMEOUT_SEC", "120"))

RAG_TOP_K = int(os.getenv("COMPLETION_RAG_TOP_K", "5"))
RAG_CHUNK_CHARS = int(os.getenv("COMPLETION_CHUNK_CHARS", "900"))
RAG_CHUNK_OVERLAP = int(os.getenv("COMPLETION_CHUNK_OVERLAP", "120"))
