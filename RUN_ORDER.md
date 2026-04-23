# KG2 Run Order (Windows + Linux)

Yes, your order is correct:

1. Run pipeline
2. Run post-processing
3. Run eval on cleaned graph (baseline)
4. Run RAG completion
5. Run eval again on completed graph

---

## Prerequisites

### Windows
- Windows 10/11
- Docker Desktop installed and running
- WSL2 enabled (Docker Desktop should use WSL2 backend)
- Docker Compose v2 (comes with Docker Desktop)
- PowerShell

Recommended checks:
- `docker --version`
- `docker compose version`
- `wsl --status`

### Linux
- Docker Engine installed and running
- Docker Compose v2 plugin
- Bash shell
- Optional GPU acceleration: NVIDIA driver + `nvidia-smi` + nvidia-container-toolkit

Recommended checks:
- `docker --version`
- `docker compose version`
- `nvidia-smi` (GPU only)

---

## Command Order

### Windows (PowerShell)

1. Pipeline
- `./run_pipeline.ps1`

2. Post-processing
- `./post_processing.ps1`

3. Eval on cleaned graph
- `./run_eval.ps1 outputs/final_clean.ttl`

4. RAG completion using cleaned graph
- `./run_completion.ps1 outputs/final_clean.ttl outputs/final_completed.ttl`

5. Eval on completed graph
- `./run_eval.ps1 outputs/final_completed.ttl`

### Linux (Bash)

1. Pipeline
- `./run_pipeline_gpu.sh`

2. Post-processing
- `./post_processing.sh`

3. Eval on cleaned graph
- `./run_eval.sh outputs/final_clean.ttl`

4. RAG completion using cleaned graph
- `./run_completion.sh outputs/final_clean.ttl outputs/final_completed.ttl`

5. Eval on completed graph
- `./run_eval.sh outputs/final_completed.ttl`

---

## Expected Artifacts

After pipeline:
- `outputs/final.ttl`

After post-processing:
- `outputs/final_clean.ttl`

After completion:
- `outputs/final_completed.ttl`
- `outputs/completion/completion_report.json`

After each eval:
- `outputs/eval_results.json` (overwritten by the next eval run)

If you want both eval result files, copy/rename `outputs/eval_results.json` after step 3 before running step 5.
