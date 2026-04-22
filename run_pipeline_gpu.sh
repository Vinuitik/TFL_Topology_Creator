#!/usr/bin/env bash
# run_pipeline_gpu.sh — GPU-accelerated pipeline runner (NVIDIA RTX 3060)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. Detect GPU ─────────────────────────────────────────────────────────────
GPU_AVAILABLE=0
TOOLKIT_READY=0

if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "Unknown")
    echo "[GPU] ✓ GPU detected: $GPU_NAME"
    GPU_AVAILABLE=1
else
    echo "[GPU] ✗ nvidia-smi not available — CPU mode"
fi

# ── 2. Ensure nvidia-ctk is configured for Docker (idempotent, ~5s) ──────────
# IMPORTANT: 'docker compose run' ignores deploy.resources reservations.
# The toolkit must be configured AND --gpus all passed explicitly on run cmds.
if [ "$GPU_AVAILABLE" -eq 1 ]; then
    if command -v nvidia-ctk &>/dev/null; then
        echo "[GPU] Configuring nvidia-ctk runtime for Docker (idempotent) …"
        sudo nvidia-ctk runtime configure --runtime=docker --set-as-default 2>/dev/null || true
        sudo systemctl restart docker 2>/dev/null || true
        echo "[GPU] ✓ nvidia-ctk runtime configured."
        TOOLKIT_READY=1
    else
        echo "[GPU] ✗ nvidia-ctk not found — installing nvidia-container-toolkit …"
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        sudo apt-get update -qq
        sudo apt-get install -y -qq nvidia-container-toolkit
        sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
        sudo systemctl restart docker
        echo "[GPU] ✓ nvidia-container-toolkit installed and configured."
        TOOLKIT_READY=1
    fi
    # Verify Docker can actually see the GPU before committing to GPU mode
    if docker run --rm --gpus all ubuntu nvidia-smi &>/dev/null 2>&1; then
        echo "[GPU] ✓ Docker GPU passthrough verified."
    else
        echo "[GPU] ⚠ Docker GPU test failed — falling back to CPU for Docker containers."
        TOOLKIT_READY=0
    fi
fi

# ── 3. Select compose files and GPU run flag ──────────────────────────────────
if [ "$TOOLKIT_READY" -eq 1 ]; then
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
    echo "[COMPOSE] Using GPU override (docker-compose.gpu.yml)"
else
    COMPOSE_FILES="-f docker-compose.yml"
    echo "[COMPOSE] Using CPU-only base (docker-compose.yml)"
fi

# ── 4. Free port 11434 (native Ollama may be running) ────────────────────────
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

# ── 5. Start supporting services ─────────────────────────────────────────────
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

# ── 6. Pull models from .env ──────────────────────────────────────────────────
echo ""
echo "[2/4] Syncing Ollama models with .env …"

# Extract model names from .env
ENTITY_MODEL=$(grep OLLAMA_ENTITY_MODEL .env | cut -d'=' -f2 | tr -d '\r')
EMBED_MODEL=$(grep OLLAMA_EMBED_MODEL .env | cut -d'=' -f2 | tr -d '\r')

MODEL_LIST=$(docker exec ollama ollama list 2>&1 || true)

for MODEL in "$ENTITY_MODEL" "$EMBED_MODEL"; do
    if [ -n "$MODEL" ]; then
        # Use awk to get the first column (NAME) and grep -x for exact match
        if ! echo "$MODEL_LIST" | awk '{print $1}' | grep -qx "$MODEL"; then
            echo "  Pulling $MODEL …"
            docker exec ollama ollama pull "$MODEL"
        else
            echo "  $MODEL already cached."
        fi
    fi
done

# ── 7. Prepare Schema ─────────────────────────────────────────────────────────
echo ""
echo "[3/4] Preparing ontology schema …"
if [ -f "final_ontology.ttl" ]; then
    mkdir -p inputs
    cp "final_ontology.ttl" "inputs/final_ontology.ttl"
    echo "  Synced final_ontology.ttl to inputs/ for ingestion."
else
    echo "  WARNING: final_ontology.ttl not found in root. Schema enforcement may be limited."
fi

# ── 8. Flush Redis for a clean run ───────────────────────────────────────────
echo ""
echo "[3.5/4] Flushing Redis for a clean run …"
docker exec redis redis-cli FLUSHALL

# ── 9. Run Ingestion ──────────────────────────────────────────────────────────
echo ""
echo "[4/4] Starting pipeline ingestion (OWL/TTL → Redis) …"
docker compose $COMPOSE_FILES run --rm --build llm-pipeline \
    python ingest_owl.py \
    --inputs-dir /app/inputs \
    --output-dir /app/outputs

# ── 9. Run pipeline over all data sources ────────────────────────────────────
echo ""
echo "[4/4] Running pipeline over all data sources (Structured + Unstructured) …"
docker compose $COMPOSE_FILES run --rm --build llm-pipeline \
    python agent.py \
    --data-dir /app/data_sources \
    --pattern "*.txt,*.json" \
    --output-dir /app/outputs

echo ""
echo "✓ Done.  Outputs in ./outputs:"
ls -lh outputs/final.ttl outputs/final.owl outputs/run_summary.json 2>/dev/null || true
