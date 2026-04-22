#!/usr/bin/env pwsh
# Run the KG evaluation against outputs/final.ttl using qwen2.5:3b + SPARQL tools.
# Prerequisites: pipeline must have run and produced outputs/final.ttl

$ErrorActionPreference = "Stop"

Write-Host "=== KG2 Evaluation ===" -ForegroundColor Cyan

# Ensure services are up (Ollama + Redis)
Write-Host "Starting services..." -ForegroundColor Yellow
docker compose up -d ollama redis
docker compose wait ollama redis 2>$null

# Run eval inside a one-shot llm-pipeline container (same image, same env)
Write-Host "Running evaluation..." -ForegroundColor Yellow
docker compose run --rm `
    -v "${PWD}/evals:/app/evals" `
    -v "${PWD}/outputs:/app/outputs" `
    --workdir /app/evals `
    llm-pipeline `
    python run_eval.py

if ($LASTEXITCODE -ne 0) {
    throw "Evaluation failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "=== Results ===" -ForegroundColor Cyan
$results = Get-Content "outputs/eval_results.json" | ConvertFrom-Json
foreach ($r in $results) {
    $status = if ($r.answer) { "[OK]" } else { "[NO ANSWER]" }
    Write-Host "$status Q$($r.id): $($r.question)" -ForegroundColor $(if ($r.answer) { "Green" } else { "Red" })
    Write-Host "     Answer:   $($r.answer)"
    Write-Host "     Expected: $($r.expected)"
    Write-Host "     Turns: $($r.turns.Count)  Time: $($r.elapsed_s)s"
    Write-Host ""
}

$answered = ($results | Where-Object { $_.answer }).Count
Write-Host "Score: $answered / $($results.Count) answered" -ForegroundColor Cyan
