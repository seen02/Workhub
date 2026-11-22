$ErrorActionPreference = 'Stop'
docker compose -f (Join-Path $PSScriptRoot 'compose.yml') --profile rag stop
if ($LASTEXITCODE -ne 0) { throw 'Docker stop failed.' }
