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
docker compose wait ollama redis 2>/dev/null || true

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
