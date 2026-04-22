#!/usr/bin/env bash
set -euo pipefail

DATA_PATTERN="${1:-Unstructured-*.txt}"

cd "$(dirname "$0")"

echo "[1/3] Building and starting Redis, Ollama, and coref-service..."
docker compose build coref-service
docker compose up -d redis ollama coref-service

if ! docker ps --filter "name=^ollama$" --format "{{.Names}}" | grep -q ollama; then
    echo "ERROR: Ollama service is not running after startup" >&2
    exit 1
fi

echo "[1.5/4] Checking Ollama models..."
MODEL_LIST=$(docker exec ollama ollama list 2>&1)

if ! echo "$MODEL_LIST" | grep -q "mxbai-embed-large"; then
    echo "  Embedding model 'mxbai-embed-large' not found, pulling..."
    docker exec ollama ollama pull mxbai-embed-large
else
    echo "  Embedding model 'mxbai-embed-large' already cached."
fi

ENTITY_MODEL=$(grep "^OLLAMA_ENTITY_MODEL=" .env | cut -d'=' -f2 | tr -d '[:space:]')
if ! echo "$MODEL_LIST" | grep -qF "$ENTITY_MODEL"; then
    echo "  Entity model '$ENTITY_MODEL' not found, pulling..."
    docker exec ollama ollama pull "$ENTITY_MODEL"
else
    echo "  Entity model '$ENTITY_MODEL' already cached."
fi

echo "[1.8/4] Flushing Redis for a clean run..."
docker exec redis redis-cli FLUSHALL

echo "[2/4] Ingesting OWL/TTL files from inputs/..."
docker compose run --rm --build llm-pipeline python ingest_owl.py --inputs-dir /app/inputs --output-dir /app/outputs

echo "[3/4] Building and running sequential pipeline..."
docker compose run --rm --build llm-pipeline python agent.py --data-dir /app/data_sources --pattern "$DATA_PATTERN" --output-dir /app/outputs

echo "[4/4] Artifacts written to ./outputs (final.owl, final.ttl, run_summary.json, runs/*)."
