#!/usr/bin/env bash
# Run the KG evaluation against outputs/final_clean.ttl (falls back to final.ttl).
# Prerequisites: pipeline must have run and produced an output graph.
set -euo pipefail

GRAPH_PATH="${1:-}"

echo "=== KG2 Evaluation ==="

# Ensure services are up
echo "Starting services..."
docker compose up -d ollama redis

# docker compose wait blocks until containers stop; use explicit readiness checks instead.
echo "Waiting for Ollama API..."
deadline=$((SECONDS + 90))
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    if [ $SECONDS -ge $deadline ]; then
        echo "ERROR: Ollama did not become ready within 90s" >&2
        exit 1
    fi
    echo "  ...still waiting for Ollama"
    sleep 2
done
echo "Ollama is ready."

# Ensure the eval model is present
ENTITY_MODEL=$(grep "^EVAL_LLM_MODEL=" .env 2>/dev/null | cut -d'=' -f2 | tr -d '\r' || echo "qwen2.5:1.5b")
echo "Checking model '$ENTITY_MODEL'..."
MODEL_LIST=$(docker compose exec -T ollama ollama list 2>&1 || true)
if ! echo "$MODEL_LIST" | awk '{print $1}' | grep -qx "$ENTITY_MODEL"; then
    echo "  Pulling '$ENTITY_MODEL'..."
    docker compose exec -T ollama ollama pull "$ENTITY_MODEL"
else
    echo "  Model '$ENTITY_MODEL' already cached."
fi

# Evict all loaded models so the eval model fits in VRAM
echo "Restarting Ollama to free VRAM..."
docker compose restart ollama
deadline2=$((SECONDS + 60))
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    [ $SECONDS -ge $deadline2 ] && { echo "ERROR: Ollama did not recover after restart" >&2; exit 1; }
    sleep 2
done
echo "Ollama restarted."

# Run eval inside a one-shot llm-pipeline container
echo "Running evaluation..."
ENV_ARGS=()
if [ -n "$GRAPH_PATH" ]; then
    BASENAME="$(basename "$GRAPH_PATH")"
    ENV_ARGS=(-e "KG_TTL_PATH=/app/outputs/${BASENAME}")
    echo "Graph override: $GRAPH_PATH"
fi
docker compose run --rm \
    -e PYTHONUNBUFFERED=1 \
    -v "${PWD}/evaluation:/app/evaluation" \
    -v "${PWD}/outputs:/app/outputs" \
    "${ENV_ARGS[@]}" \
    --workdir /app/evaluation \
    llm-pipeline \
    python -u run_eval.py

echo ""
echo "=== Results ==="
python3 - <<'EOF'
import json, sys
from pathlib import Path

data = json.loads(Path("outputs/eval_results.json").read_text())
s = data["summary"]
print(f"Score: {s['score']}  |  Accuracy: {float(s['accuracy'])*100:.1f}%")
print(f"By type: {s['by_type']}")
print()
for r in data["results"]:
    mark = "PASS" if r["correct"] else "FAIL"
    print(f"[{mark}] Q{r['id']} [{r['expected_type']}]: {r['question']}")
    print(f"       Answer: {r['answer']}")
    print(f"       Detail: {r['score_detail']}")
    print(f"       Turns: {len(r['turns'])}  Time: {r['elapsed_s']}s")
    print()
EOF
