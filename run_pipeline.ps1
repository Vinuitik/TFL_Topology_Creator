param(
    [string]$DataPattern = "Unstructured-*.txt"
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
if ($modelList -notmatch "mxbai-embed-large") {
    Write-Host "  Embedding model 'mxbai-embed-large' not found, pulling..."
    docker exec ollama ollama pull mxbai-embed-large
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull mxbai-embed-large in ollama container" }
} else {
    Write-Host "  Embedding model 'mxbai-embed-large' already cached."
}
$entityModel = (Get-Content .env | Select-String "^OLLAMA_ENTITY_MODEL=").ToString().Split("=")[1].Trim()
if ($modelList -notmatch [regex]::Escape($entityModel)) {
    Write-Host "  Entity model '$entityModel' not found, pulling..."
    docker exec ollama ollama pull $entityModel
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull $entityModel in ollama container" }
} else {
    Write-Host "  Entity model '$entityModel' already cached."
}

Write-Host "[1.8/4] Flushing Redis for a clean run..."
docker exec redis redis-cli FLUSHALL
if ($LASTEXITCODE -ne 0) {
    throw "Redis flush failed with exit code $LASTEXITCODE"
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
