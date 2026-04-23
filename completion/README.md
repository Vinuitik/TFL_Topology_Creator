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

Optional graph overrides:

- Windows: `./run_completion.ps1 outputs/final_clean.ttl outputs/final_completed.ttl`
- Linux: `./run_completion.sh outputs/final_clean.ttl outputs/final_completed.ttl`

If no args are passed, completion uses `outputs/final.ttl` as input and writes `outputs/final_completed.ttl`.

## Evaluate Both Graphs

Baseline:

- Windows: `./run_eval.ps1 outputs/final.ttl`
- Linux: `./run_eval.sh outputs/final.ttl`

Completed:

- Windows: `./run_eval.ps1 outputs/final_completed.ttl`
- Linux: `./run_eval.sh outputs/final_completed.ttl`

If no path is passed, eval still follows default behavior (`final_clean.ttl` then `final.ttl`).
