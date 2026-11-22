$ErrorActionPreference = 'Stop'
$ragEnabled = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '.env') -ErrorAction SilentlyContinue) -match '^RAG_ENABLED=true\s*$'
if ($ragEnabled) {
    docker compose -f (Join-Path $PSScriptRoot 'compose.yml') --profile rag up -d --wait
} else {
    docker compose -f (Join-Path $PSScriptRoot 'compose.yml') up -d --wait
}
if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. Check Docker Desktop.' }
Write-Host 'Document assistant: http://localhost:3002'
Write-Host 'Open WebUI: http://localhost:3001'
