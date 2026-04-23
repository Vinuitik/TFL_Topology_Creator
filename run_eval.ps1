#!/usr/bin/env pwsh
# Run the KG evaluation against outputs/final_clean.ttl (falls back to final.ttl).
# Prerequisites: pipeline must have run and produced an output graph.

$ErrorActionPreference = "Stop"

Write-Host "=== KG2 Evaluation ===" -ForegroundColor Cyan

# Ensure services are up (Ollama + Redis)
Write-Host "Starting services..." -ForegroundColor Yellow
docker compose up -d ollama redis
docker compose wait ollama redis 2>$null

# Run eval inside a one-shot llm-pipeline container (same image, same env)
Write-Host "Running evaluation..." -ForegroundColor Yellow
docker compose run --rm `
    -v "${PWD}/evaluation:/app/evaluation" `
    -v "${PWD}/outputs:/app/outputs" `
    --workdir /app/evaluation `
    llm-pipeline `
    python run_eval.py

if ($LASTEXITCODE -ne 0) {
    throw "Evaluation failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "=== Results ===" -ForegroundColor Cyan
$data = Get-Content "outputs/eval_results.json" | ConvertFrom-Json
$summary = $data.summary
$results = $data.results

Write-Host "Score: $($summary.score)  |  Accuracy: $([math]::Round($summary.accuracy * 100, 1))%" `
    -ForegroundColor Cyan
Write-Host "By type: $($summary.by_type | ConvertTo-Json -Compress)" -ForegroundColor Cyan
Write-Host ""

foreach ($r in $results) {
    $mark  = if ($r.correct) { "[PASS]" } else { "[FAIL]" }
    $color = if ($r.correct) { "Green" } else { "Red" }
    Write-Host "$mark Q$($r.id) [$($r.expected_type)]: $($r.question)" -ForegroundColor $color
    Write-Host "     Answer:  $($r.answer)"
    Write-Host "     Detail:  $($r.score_detail)"
    Write-Host "     Turns: $($r.turns.Count)  Time: $($r.elapsed_s)s"
    Write-Host ""
}
