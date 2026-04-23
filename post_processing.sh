#!/usr/bin/env bash
# post_processing.sh — KG2 post-processing runner (Linux / Kishan's setup)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=== KG2 Post-Processing (Linux) ==="
echo ""

# ---------------------------------------------------------------------------
# Helper: read a value from .env (last non-commented match wins)
# ---------------------------------------------------------------------------
parse_env() {
    local key=$1 default=$2
    local val
    val=$(grep -E "^${key}=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r"'"'")
    echo "${val:-$default}"
}

DEFAULT_MODEL=$(parse_env "OLLAMA_ENTITY_MODEL" "qwen2.5:3b")
POST_LLM_MODEL=$(parse_env "POST_LLM_MODEL" "$DEFAULT_MODEL")
echo "Post-processing LLM: $POST_LLM_MODEL"

# ---------------------------------------------------------------------------
# Select compose files (GPU if available)
# ---------------------------------------------------------------------------
COMPOSE_FILES="-f docker-compose.yml"
if [ -f "docker-compose.gpu.yml" ]; then
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
        echo "GPU detected — using docker-compose.gpu.yml"
    fi
fi

# ---------------------------------------------------------------------------
# Ensure required services are running
# ---------------------------------------------------------------------------
ensure_running() {
    local service=$1
    if docker compose $COMPOSE_FILES ps --status running --services 2>/dev/null | grep -q "^${service}$"; then
        echo "$service is already running."
    else
        echo "Starting $service..."
        docker compose $COMPOSE_FILES up -d "$service"
    fi
}

ensure_running redis
ensure_running ollama

# Wait for Ollama HTTP to become ready (up to 60 s)
echo "Waiting for Ollama to be ready..."
deadline=$((SECONDS + 60))
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    if [ $SECONDS -ge $deadline ]; then
        echo "ERROR: Ollama did not become ready within 60 s" >&2
        exit 1
    fi
    sleep 2
done
echo "Ollama is ready."

# ---------------------------------------------------------------------------
# Pull POST_LLM_MODEL if not already present
# ---------------------------------------------------------------------------
echo "Checking if model '$POST_LLM_MODEL' is available..."
MODEL_BASE="${POST_LLM_MODEL%%:*}"
if ! docker compose $COMPOSE_FILES exec -T ollama ollama list 2>/dev/null | grep -q "$MODEL_BASE"; then
    echo "Pulling model '$POST_LLM_MODEL'..."
    docker compose $COMPOSE_FILES exec -T ollama ollama pull "$POST_LLM_MODEL"
else
    echo "Model '$POST_LLM_MODEL' already present."
fi

# ---------------------------------------------------------------------------
# Stage final_ontology.ttl into inputs/
# ---------------------------------------------------------------------------
if [ ! -f "final_ontology.ttl" ]; then
    echo "ERROR: final_ontology.ttl not found in project root" >&2
    exit 1
fi
mkdir -p inputs
cp "final_ontology.ttl" "inputs/final_ontology.ttl"
echo "Staged final_ontology.ttl → inputs/"

# ---------------------------------------------------------------------------
# Run post-processing inside the llm-pipeline image
# --no-deps: Redis/Ollama already up above
# ---------------------------------------------------------------------------
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
