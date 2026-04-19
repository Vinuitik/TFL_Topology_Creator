param(
    [string]$DataPattern = "Unstructured-*.txt",
    [string]$Model = "gemma2:2b"
)

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot"

Write-Host "[1/3] Building and starting Redis, Ollama, and coref-service..."
docker compose build coref-service
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build coref-service"
}
docker compose up -d redis ollama coref-service
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start redis/ollama/coref-service"
}

$ollamaIsUp = docker ps --filter "name=^ollama$" --format "{{.Names}}"
if (-not $ollamaIsUp) {
    throw "Ollama service is not running after startup"
}

Write-Host "[1.5/4] Checking Ollama models..."
$modelList = docker exec ollama ollama list 2>&1
if ($modelList -notmatch [regex]::Escape($Model)) {
    Write-Host "  LLM model '$Model' not found, pulling..."
    docker exec ollama ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull model '$Model' in ollama container" }
} else {
    Write-Host "  LLM model '$Model' already cached."
}
if ($modelList -notmatch "nomic-embed-text") {
    Write-Host "  Embedding model 'nomic-embed-text' not found, pulling..."
    docker exec ollama ollama pull nomic-embed-text
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull nomic-embed-text in ollama container" }
} else {
    Write-Host "  Embedding model 'nomic-embed-text' already cached."
}
if ($modelList -notmatch "qwen2.5:1.5b") {
    Write-Host "  Entity model 'qwen2.5:1.5b' not found, pulling..."
    docker exec ollama ollama pull qwen2.5:1.5b
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull qwen2.5:1.5b in ollama container" }
} else {
    Write-Host "  Entity model 'qwen2.5:1.5b' already cached."
}

Write-Host "[2/4] Ingesting OWL/TTL files from inputs/..."
docker compose run --rm --build llm-pipeline python ingest_owl.py --inputs-dir /app/inputs --output-dir /app/outputs
if ($LASTEXITCODE -ne 0) {
    throw "OWL ingestion failed with exit code $LASTEXITCODE"
}

Write-Host "[3/4] Building and running sequential pipeline..."
docker compose run --rm --build llm-pipeline python agent.py --data-dir /app/data_sources --pattern $DataPattern --output-dir /app/outputs
if ($LASTEXITCODE -ne 0) {
    throw "Pipeline run failed with exit code $LASTEXITCODE"
}

Write-Host "[4/4] Artifacts written to ./outputs (final.owl, final.ttl, run_summary.json, runs/*)."
