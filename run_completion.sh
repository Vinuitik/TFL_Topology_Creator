#!/usr/bin/env bash
set -euo pipefail

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
  --workdir /app/completion \
  llm-pipeline \
  python run_completion.py

echo ""
echo "Done."
echo "Output: outputs/final_completed.ttl"
echo "Report: outputs/completion/completion_report.json"
