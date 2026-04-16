param(
    [string]$DataPattern = "Unstructured-*.txt",
    [string]$Model = "gemma4:e4b"
)

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot"

Write-Host "[1/3] Starting Redis and Ollama services..."
docker compose up -d redis ollama
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start redis/ollama services"
}

$ollamaIsUp = docker ps --filter "name=^ollama$" --format "{{.Names}}"
if (-not $ollamaIsUp) {
    throw "Ollama service is not running after startup"
}

Write-Host "[1.5/3] Checking Ollama model: $Model"
$modelList = docker exec ollama ollama list 2>&1
if ($modelList -notmatch [regex]::Escape($Model)) {
    Write-Host "  Model not found locally, pulling..."
    docker exec ollama ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull model '$Model' in ollama container"
    }
} else {
    Write-Host "  Model already cached, skipping pull."
}

Write-Host "[2/3] Building and running sequential pipeline..."
docker compose run --rm --build llm-pipeline python agent.py --data-dir /app/data_sources --pattern $DataPattern --output-dir /app/outputs
if ($LASTEXITCODE -ne 0) {
    throw "Pipeline run failed with exit code $LASTEXITCODE"
}

Write-Host "[3/3] Artifacts written to ./outputs (final.owl, final.ttl, run_summary.json, runs/*)."
