param()

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot"

Write-Host ""
Write-Host "=== KG2 Post-Processing (Windows) ==="
Write-Host "Assumes Redis and Ollama containers are already running."
Write-Host ""

# Stage final_ontology.ttl into inputs/ so it is reachable inside the container
if (-not (Test-Path "final_ontology.ttl")) {
    throw "final_ontology.ttl not found in project root"
}
if (-not (Test-Path "inputs")) { New-Item -ItemType Directory -Path "inputs" | Out-Null }
Copy-Item "final_ontology.ttl" "inputs\final_ontology.ttl" -Force
Write-Host "Staged final_ontology.ttl → inputs/"

# Run post-processing inside the llm-pipeline image
# --no-deps: do not start Redis/Ollama/coref (assumed already up)
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
