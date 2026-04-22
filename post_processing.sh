#!/usr/bin/env bash
# post_processing.sh — KG2 post-processing runner (Linux / Kishan's setup)
# Assumes Redis and Ollama containers are already running.
# ---------------------------------------------------------------------------
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=== KG2 Post-Processing (Linux) ==="
echo "Assumes Redis and Ollama containers are already running."
echo ""

# Stage final_ontology.ttl into inputs/ so it is reachable inside the container
if [ ! -f "final_ontology.ttl" ]; then
    echo "ERROR: final_ontology.ttl not found in project root" >&2
    exit 1
fi
mkdir -p inputs
cp "final_ontology.ttl" "inputs/final_ontology.ttl"
echo "Staged final_ontology.ttl → inputs/"

# Select compose files (GPU if available, else CPU)
COMPOSE_FILES="-f docker-compose.yml"
if [ -f "docker-compose.gpu.yml" ]; then
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
        echo "GPU detected — using docker-compose.gpu.yml"
    fi
fi

# Run post-processing inside the llm-pipeline image
# --no-deps: do not start Redis/Ollama/coref (assumed already up)
docker compose $COMPOSE_FILES run --rm --no-deps \
    -v "$(pwd)/postprocessing:/app/postprocessing" \
    llm-pipeline \
    python /app/postprocessing/post_process.py \
    --input /app/outputs/final.ttl \
    --ontology /app/inputs/final_ontology.ttl \
    --output /app/outputs/final_clean.ttl

echo ""
echo "Done!  Output: outputs/final_clean.ttl"
ls -lh outputs/final_clean.ttl 2>/dev/null || true
