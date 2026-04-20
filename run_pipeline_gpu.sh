#!/usr/bin/env bash
# run_pipeline_gpu.sh — GPU-accelerated pipeline runner (NVIDIA RTX 3060)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. Detect GPU and Container Toolkit ──────────────────────────────────────
GPU_AVAILABLE=0
TOOLKIT_READY=0

if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "Unknown")
    echo "[GPU] ✓ GPU detected: $GPU_NAME"
    GPU_AVAILABLE=1
else
    echo "[GPU] ✗ nvidia-smi not available — CPU mode"
fi

# In WSL2 with Docker Desktop, the toolkit is handled transparently.
# If nvidia-smi works, we assume the GPU is available for Docker.
if [ "$GPU_AVAILABLE" -eq 1 ]; then
    echo "[GPU] ✓ Assuming Docker Desktop WSL2 GPU passthrough is enabled"
    TOOLKIT_READY=1
fi

# ── 2. Select compose files ───────────────────────────────────────────────────
if [ "$TOOLKIT_READY" -eq 1 ]; then
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
    echo "[COMPOSE] Using GPU override (docker-compose.gpu.yml)"
else
    COMPOSE_FILES="-f docker-compose.yml"
    echo "[COMPOSE] Using CPU-only base (docker-compose.yml)"
fi

# ── 3. Free port 11434 (native Ollama may be running) ────────────────────────
echo ""
echo "[PRE] Checking port 11434 …"
if ss -tlnp 2>/dev/null | grep -q ':11434'; then
    echo "[PRE] Port 11434 in use — stopping native Ollama …"
    sudo systemctl stop ollama 2>/dev/null || true
    sleep 1
    sudo fuser -k 11434/tcp 2>/dev/null || true
    sleep 1
    echo "[PRE] Port 11434 is free."
else
    echo "[PRE] Port 11434 is free."
fi

# ── 3. Start supporting services ──────────────────────────────────────────────
echo ""
echo "[1/4] Building and starting Redis, Ollama, and coref-service …"
docker compose $COMPOSE_FILES build coref-service llm-pipeline
docker compose $COMPOSE_FILES up -d redis ollama coref-service

echo "[1/4] Waiting for Ollama to be healthy …"
until docker exec ollama ollama list > /dev/null 2>&1; do
    printf "."
    sleep 3
done
echo " up."

# ── 4. Pull models ────────────────────────────────────────────────────────────
echo ""
echo "[2/4] Checking Ollama models …"
MODEL_LIST=$(docker exec ollama ollama list 2>&1 || true)

for MODEL in "nomic-embed-text" "qwen2.5:1.5b"; do
    if ! echo "$MODEL_LIST" | grep -q "${MODEL%%:*}"; then
        echo "  Pulling $MODEL …"
        docker exec ollama ollama pull "$MODEL"
    else
        echo "  $MODEL already cached."
    fi
done

# ── 5. Ingest ontology ────────────────────────────────────────────────────────
echo ""
echo "[3/4] Ingesting OWL/TTL ontology …"
docker compose $COMPOSE_FILES run --rm llm-pipeline \
    python ingest_owl.py \
    --inputs-dir /app/inputs \
    --output-dir /app/outputs

# ── 6. Run pipeline over all data sources ─────────────────────────────────────
echo ""
echo "[4/4] Running pipeline over all data sources (Structured + Unstructured) …"
docker compose $COMPOSE_FILES run --rm llm-pipeline \
    python agent.py \
    --data-dir /app/data_sources \
    --pattern "*.txt,*.json" \
    --output-dir /app/outputs

echo ""
echo "✓ Done.  Outputs in ./outputs:"
ls -lh outputs/final.ttl outputs/final.owl outputs/run_summary.json 2>/dev/null || true
