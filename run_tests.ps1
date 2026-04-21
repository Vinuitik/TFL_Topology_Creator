Set-Location "$PSScriptRoot\llm_pipeline"

# Use the Python from the local venv if present, otherwise fall back to system python
$venvPython = "$PSScriptRoot\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m pytest tests/ -s -v
} else {
    python -m pytest tests/ -s -v
}
