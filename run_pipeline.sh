#!/usr/bin/env bash
# run_pipeline.sh — WSL pipeline runner
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parameters
DATA_PATTERN="${1:-Unstructured-*.txt}"

echo "[1/4] Building and starting Redis, Ollama, and coref-service..."
docker compose build coref-service
docker compose up -d redis ollama coref-service

echo "Waiting for Ollama to be healthy..."
until docker exec ollama ollama list > /dev/null 2>&1; do
    printf "."
    sleep 2
done
echo " up."

echo "[1.5/4] Checking Ollama models..."
MODEL_LIST=$(docker exec ollama ollama list 2>&1 || true)

# Pull embedding model
if ! echo "$MODEL_LIST" | grep -q "mxbai-embed-large"; then
    echo "  Embedding model 'mxbai-embed-large' not found, pulling..."
    docker exec ollama ollama pull mxbai-embed-large
else
    echo "  Embedding model 'mxbai-embed-large' already cached."
fi

# Pull entity model from .env
ENTITY_MODEL=$(grep "^OLLAMA_ENTITY_MODEL=" .env | cut -d'=' -f2 | tr -d '\r' | xargs)
if [[ -z "$ENTITY_MODEL" ]]; then
    echo "Warning: OLLAMA_ENTITY_MODEL not found in .env, skipping pull."
elif ! echo "$MODEL_LIST" | grep -q "${ENTITY_MODEL%%:*}"; then
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

echo ""
echo "[4/4] Artifacts written to ./outputs (final.owl, final.ttl, run_summary.json, runs/*)."
