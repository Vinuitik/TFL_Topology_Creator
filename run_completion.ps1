#!/usr/bin/env pwsh
param(
    [string]$GraphPath = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

Write-Host "=== KG2 Completion ===" -ForegroundColor Cyan

Write-Host "Starting services..." -ForegroundColor Yellow
docker compose up -d ollama redis

Write-Host "Waiting for Ollama API..." -ForegroundColor Yellow
$deadline = (Get-Date).AddSeconds(90); $ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        $ready = $true; break
    } catch { Write-Host "  ...still waiting for Ollama" -ForegroundColor DarkYellow; Start-Sleep -Seconds 2 }
}
if (-not $ready) { throw "Ollama did not become ready within 90 seconds" }
Write-Host "Ollama is ready." -ForegroundColor Green

function Get-EnvValue($key, $default) {
    $line = Get-Content .env -ErrorAction SilentlyContinue |
            Where-Object { $_ -match "^$key=" } | Select-Object -First 1
    if ($line) { return $line.Split("=", 2)[1].Trim() } else { return $default }
}
$completionModel = Get-EnvValue "OLLAMA_ENTITY_MODEL" "qwen2.5:3b"
Write-Host "Checking model '$completionModel'..." -ForegroundColor Yellow
$modelList = docker compose exec -T ollama ollama list 2>$null
if ($modelList -notmatch [regex]::Escape(($completionModel -split ":")[0])) {
    Write-Host "  Pulling '$completionModel'..." -ForegroundColor Yellow
    docker compose exec -T ollama ollama pull $completionModel
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull model $completionModel" }
} else { Write-Host "  Model '$completionModel' already cached." -ForegroundColor Green }

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

Write-Host "Running completion pipeline..." -ForegroundColor Yellow
$envArgs = @()
$outputName = "final_completed.ttl"

if ($GraphPath -and $GraphPath.Trim() -ne "") {
    $resolvedGraph = Resolve-Path $GraphPath
    $envArgs += @("-e", "KG_INPUT_PATH=/app/outputs/$([System.IO.Path]::GetFileName($resolvedGraph.Path))")
    Write-Host "Input graph override: $($resolvedGraph.Path)" -ForegroundColor Yellow
}

if ($OutputPath -and $OutputPath.Trim() -ne "") {
    $outputName = [System.IO.Path]::GetFileName($OutputPath)
    $envArgs += @("-e", "KG_OUTPUT_PATH=/app/outputs/$outputName")
    Write-Host "Output graph override: outputs/$outputName" -ForegroundColor Yellow
}

docker compose run --rm `
    -v "${PWD}/completion:/app/completion" `
    -v "${PWD}/data_sources:/app/data_sources" `
    -v "${PWD}/outputs:/app/outputs" `
    -v "${PWD}/final_ontology.ttl:/app/final_ontology.ttl" `
    @envArgs `
    --workdir /app/completion `
    llm-pipeline `
    python run_completion.py

if ($LASTEXITCODE -ne 0) {
    throw "Completion failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Output: outputs/$outputName"
Write-Host "Report: outputs/completion/completion_report.json"
