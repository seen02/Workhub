param([switch]$Build)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$composeFile = Join-Path $projectRoot '.local/permissions-compose.json'
if (!(Test-Path -LiteralPath $composeFile)) { throw 'The prepared local permissions configuration is missing.' }
if ($Build) {
    docker build -f (Join-Path $PSScriptRoot 'Dockerfile.permissions-workhub') -t workhub-dev/workhub:permissions $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Workhub build failed.' }
    docker build -f (Join-Path $PSScriptRoot 'Dockerfile.permissions-document-agent') -t workhub-dev/document-agent:permissions $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Document agent build failed.' }
}
docker compose -p workhub-permissions -f $composeFile up -d --no-build
if ($LASTEXITCODE -ne 0) { throw 'Start failed. Make sure the original and deployment rehearsal stacks are stopped.' }
Write-Host 'Local permissions stack started. Workhub: http://localhost:8004'
