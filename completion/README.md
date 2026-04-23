# KG Completion (RAG)

This module fills missing KG facts using retrieval over `data_sources/` plus `qwen2.5:3b`.

## What It Produces

- `outputs/final_completed.ttl` (new graph; source graph is untouched)
- `outputs/completion/rag_index.json`
- `outputs/completion/gaps.json`
- `outputs/completion/proposals.json`
- `outputs/completion/completion_report.json`

## One-Command Run

From project root:

- Windows: `./run_completion.ps1`
- Linux: `./run_completion.sh`

## Evaluate Both Graphs

Baseline:

- Windows: `./run_eval.ps1 outputs/final.ttl`
- Linux: `./run_eval.sh outputs/final.ttl`

Completed:

- Windows: `./run_eval.ps1 outputs/final_completed.ttl`
- Linux: `./run_eval.sh outputs/final_completed.ttl`

If no path is passed, eval still follows default behavior (`final_clean.ttl` then `final.ttl`).
