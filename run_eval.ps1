#!/usr/bin/env pwsh
param(
    [string]$GraphPath = ""
)

# Run the KG evaluation against outputs/final_clean.ttl (falls back to final.ttl).
# Prerequisites: pipeline must have run and produced an output graph.

$ErrorActionPreference = "Stop"

Write-Host "=== KG2 Evaluation ===" -ForegroundColor Cyan

# Ensure services are up (Ollama + Redis)
Write-Host "Starting services..." -ForegroundColor Yellow
docker compose up -d ollama redis

# docker compose wait blocks until containers stop; use explicit readiness checks instead.
Write-Host "Waiting for Ollama API..." -ForegroundColor Yellow
$deadline = (Get-Date).AddSeconds(90)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        $ready = $true
        break
    }
    catch {
        Write-Host "  ...still waiting for Ollama" -ForegroundColor DarkYellow
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    throw "Ollama did not become ready within 90 seconds"
}
Write-Host "Ollama is ready." -ForegroundColor Green

# Ensure the eval model is present
function Get-EnvValue($key, $default) {
    $line = Get-Content .env -ErrorAction SilentlyContinue |
            Where-Object { $_ -match "^$key=" } |
            Select-Object -First 1
    if ($line) { return $line.Split("=", 2)[1].Trim() } else { return $default }
}
$evalModel = Get-EnvValue "OLLAMA_ENTITY_MODEL" "qwen2.5:3b"
Write-Host "Checking model '$evalModel'..." -ForegroundColor Yellow
$modelList  = docker compose exec -T ollama ollama list 2>$null
$modelBase  = ($evalModel -split ":")[0]
if ($modelList -notmatch [regex]::Escape($modelBase)) {
    Write-Host "  Pulling '$evalModel'..." -ForegroundColor Yellow
    docker compose exec -T ollama ollama pull $evalModel
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull model $evalModel" }
    Write-Host "  Model pulled." -ForegroundColor Green
} else {
    Write-Host "  Model '$evalModel' already cached." -ForegroundColor Green
}

# Evict all loaded models so the eval model fits in VRAM
Write-Host "Restarting Ollama to free VRAM..." -ForegroundColor Yellow
docker compose restart ollama
$deadline2 = (Get-Date).AddSeconds(60); $ready2 = $false
while ((Get-Date) -lt $deadline2) {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        $ready2 = $true; break
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready2) { throw "Ollama did not recover after restart" }
Write-Host "Ollama restarted." -ForegroundColor Green

# Run eval inside a one-shot llm-pipeline container (same image, same env)
Write-Host "Running evaluation..." -ForegroundColor Yellow

$envArgs = @()
if ($GraphPath -and $GraphPath.Trim() -ne "") {
    $resolvedGraph = Resolve-Path $GraphPath
    $envArgs = @("-e", "KG_TTL_PATH=/app/outputs/$([System.IO.Path]::GetFileName($resolvedGraph.Path))")
    Write-Host "Graph override: $($resolvedGraph.Path)" -ForegroundColor Yellow
}

docker compose run --rm `
    -e PYTHONUNBUFFERED=1 `
    -v "${PWD}/evaluation:/app/evaluation" `
    -v "${PWD}/outputs:/app/outputs" `
    @envArgs `
    --workdir /app/evaluation `
    llm-pipeline `
    python -u run_eval.py

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
