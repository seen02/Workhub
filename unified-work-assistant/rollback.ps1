$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.local/migration.json') -Raw | ConvertFrom-Json
docker compose -f (Join-Path $PSScriptRoot 'compose.yml') --profile '*' stop
if ($LASTEXITCODE -ne 0) { throw 'Cannot resume originals while new services may be writing.' }
# Rollback restores the pre-migration state, not changes made in the new project.
docker start @($manifest.original_containers)
if ($LASTEXITCODE -ne 0) { throw 'Original container restart failed.' }
