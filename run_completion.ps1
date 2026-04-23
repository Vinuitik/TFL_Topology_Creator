#!/usr/bin/env pwsh
param(
    [string]$GraphPath = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

Write-Host "=== KG2 Completion ===" -ForegroundColor Cyan

Write-Host "Starting services..." -ForegroundColor Yellow
docker compose up -d ollama redis
docker compose wait ollama redis 2>$null

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
