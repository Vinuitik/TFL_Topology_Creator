#!/usr/bin/env bash
# Run the KG evaluation against outputs/final_clean.ttl (falls back to final.ttl).
# Prerequisites: pipeline must have run and produced an output graph.
set -euo pipefail

GRAPH_PATH="${1:-}"

echo "=== KG2 Evaluation ==="

# Ensure services are up
echo "Starting services..."
docker compose up -d ollama redis
docker compose wait ollama redis 2>/dev/null || true

# Run eval inside a one-shot llm-pipeline container
echo "Running evaluation..."
ENV_ARGS=()
if [ -n "$GRAPH_PATH" ]; then
    BASENAME="$(basename "$GRAPH_PATH")"
    ENV_ARGS=(-e "KG_TTL_PATH=/app/outputs/${BASENAME}")
    echo "Graph override: $GRAPH_PATH"
fi
docker compose run --rm \
    -v "${PWD}/evaluation:/app/evaluation" \
    -v "${PWD}/outputs:/app/outputs" \
    "${ENV_ARGS[@]}" \
    --workdir /app/evaluation \
    llm-pipeline \
    python run_eval.py

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
