param()

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot"

Write-Host ""
Write-Host "=== KG2 Post-Processing (Windows) ==="
Write-Host ""

# ---------------------------------------------------------------------------
# Helper: read a value from .env (last non-commented match wins)
# ---------------------------------------------------------------------------
function Get-EnvValue($key, $default) {
    $line = Get-Content ".env" -ErrorAction SilentlyContinue |
            Where-Object { $_ -match "^$key=" } |
            Select-Object -Last 1
    if ($line) { return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'") }
    return $default
}

$defaultModel   = Get-EnvValue "OLLAMA_ENTITY_MODEL" "qwen2.5:3b"
$POST_LLM_MODEL = Get-EnvValue "POST_LLM_MODEL" $defaultModel
Write-Host "Post-processing LLM: $POST_LLM_MODEL"

# ---------------------------------------------------------------------------
# Ensure required services are running
# ---------------------------------------------------------------------------
function Ensure-ServiceRunning($service) {
    $running = docker compose ps --status running --services 2>$null
    if ($running -notmatch "(?m)^$service`$") {
        Write-Host "Starting $service..."
        docker compose up -d $service
        if ($LASTEXITCODE -ne 0) { throw "Failed to start $service" }
    } else {
        Write-Host "$service is already running."
    }
}

Ensure-ServiceRunning "redis"
Ensure-ServiceRunning "ollama"

# Wait for Ollama HTTP to become ready (up to 60 s)
Write-Host "Waiting for Ollama to be ready..."
$deadline = (Get-Date).AddSeconds(60)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) { throw "Ollama did not become ready within 60 s" }
Write-Host "Ollama is ready."

# ---------------------------------------------------------------------------
# Pull POST_LLM_MODEL if not already present
# ---------------------------------------------------------------------------
Write-Host "Checking if model '$POST_LLM_MODEL' is available..."
$modelList = docker compose exec -T ollama ollama list 2>$null
$modelBase = ($POST_LLM_MODEL -split ":")[0]
if ($modelList -notmatch [regex]::Escape($modelBase)) {
    Write-Host "Pulling model '$POST_LLM_MODEL'..."
    docker compose exec -T ollama ollama pull $POST_LLM_MODEL
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull model $POST_LLM_MODEL" }
} else {
    Write-Host "Model '$POST_LLM_MODEL' already present."
}

# ---------------------------------------------------------------------------
# Stage final_ontology.ttl into inputs/
# ---------------------------------------------------------------------------
if (-not (Test-Path "final_ontology.ttl")) {
    throw "final_ontology.ttl not found in project root"
}
if (-not (Test-Path "inputs")) { New-Item -ItemType Directory -Path "inputs" | Out-Null }
Copy-Item "final_ontology.ttl" "inputs\final_ontology.ttl" -Force
Write-Host "Staged final_ontology.ttl → inputs/"

# ---------------------------------------------------------------------------
# Run post-processing inside the llm-pipeline image
# --no-deps: Redis/Ollama already up above
# ---------------------------------------------------------------------------
docker compose run --rm --no-deps `
    -v "${PSScriptRoot}/postprocessing:/app/postprocessing" `
    llm-pipeline `
    python /app/postprocessing/post_process.py `
    --input /app/outputs/final.ttl `
    --ontology /app/inputs/final_ontology.ttl `
    --output /app/outputs/final_clean.ttl
if ($LASTEXITCODE -ne 0) { throw "Post-processing failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Done!  Output: outputs/final_clean.ttl"
