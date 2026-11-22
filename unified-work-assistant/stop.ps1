$ErrorActionPreference = 'Stop'
docker compose -f (Join-Path $PSScriptRoot 'compose.yml') --profile '*' stop
if ($LASTEXITCODE -ne 0) { throw 'Unified project stop failed.' }
