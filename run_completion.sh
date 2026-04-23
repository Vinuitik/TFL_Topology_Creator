#!/usr/bin/env bash
set -euo pipefail

GRAPH_PATH="${1:-}"
OUTPUT_PATH="${2:-}"
OUTPUT_NAME="final_completed.ttl"

ENV_ARGS=()
if [ -n "$GRAPH_PATH" ]; then
  BASENAME="$(basename "$GRAPH_PATH")"
  ENV_ARGS+=(-e "KG_INPUT_PATH=/app/outputs/${BASENAME}")
  echo "Input graph override: ${GRAPH_PATH}"
fi
if [ -n "$OUTPUT_PATH" ]; then
  OUTPUT_NAME="$(basename "$OUTPUT_PATH")"
  ENV_ARGS+=(-e "KG_OUTPUT_PATH=/app/outputs/${OUTPUT_NAME}")
  echo "Output graph override: outputs/${OUTPUT_NAME}"
fi

echo "=== KG2 Completion ==="

echo "Starting services..."
docker compose up -d ollama redis

echo "Waiting for Ollama API..."
deadline=$((SECONDS + 90))
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    [ $SECONDS -ge $deadline ] && { echo "ERROR: Ollama not ready in 90s" >&2; exit 1; }
    echo "  ...still waiting"; sleep 2
done
echo "Ollama is ready."

ENTITY_MODEL=$(grep "^OLLAMA_ENTITY_MODEL=" .env 2>/dev/null | cut -d'=' -f2 | tr -d '\r' || echo "qwen2.5:3b")
echo "Checking model '$ENTITY_MODEL'..."
MODEL_LIST=$(docker compose exec -T ollama ollama list 2>&1 || true)
if ! echo "$MODEL_LIST" | awk '{print $1}' | grep -qx "$ENTITY_MODEL"; then
    echo "  Pulling '$ENTITY_MODEL'..."; docker compose exec -T ollama ollama pull "$ENTITY_MODEL"
else
    echo "  Model '$ENTITY_MODEL' already cached."
fi

echo "Restarting Ollama to free VRAM..."
docker compose restart ollama
deadline2=$((SECONDS + 60))
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    [ $SECONDS -ge $deadline2 ] && { echo "ERROR: Ollama did not recover after restart" >&2; exit 1; }
    sleep 2
done
echo "Ollama restarted."

echo "Running completion pipeline..."
docker compose run --rm \
  -v "${PWD}/completion:/app/completion" \
  -v "${PWD}/data_sources:/app/data_sources" \
  -v "${PWD}/outputs:/app/outputs" \
  -v "${PWD}/final_ontology.ttl:/app/final_ontology.ttl" \
  "${ENV_ARGS[@]}" \
  --workdir /app/completion \
  llm-pipeline \
  python run_completion.py

echo ""
echo "Done."
echo "Output: outputs/${OUTPUT_NAME}"
echo "Report: outputs/completion/completion_report.json"
