$ErrorActionPreference = 'Stop'
$composeFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.local/permissions-compose.json'
docker compose -p workhub-permissions -f $composeFile stop --timeout 45
if ($LASTEXITCODE -ne 0) { throw 'Stop failed.' }
Write-Host 'Stopped. All local permissions containers and data were preserved.'
