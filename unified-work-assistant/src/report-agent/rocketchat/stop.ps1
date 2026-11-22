param([switch]$BotOnly, [switch]$ReviewOnly)

$ErrorActionPreference = 'Stop'
$localPath = Join-Path $PSScriptRoot '.local'
$composePath = Join-Path $PSScriptRoot 'compose.yml'
$composeEnv = Join-Path $localPath 'compose.env'

if ($BotOnly) {
    docker compose --env-file $composeEnv -f $composePath stop worker
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop report-bot.' }
    Write-Host 'Containerized report-bot stopped.'
    return
}
if ($ReviewOnly) {
    docker compose --env-file $composeEnv -f $composePath stop review
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop review API.' }
    Write-Host 'Containerized report review API stopped.'
    return
}

docker compose --env-file $composeEnv -f $composePath stop
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the local chat containers.' }
Write-Host 'Rocket.Chat, databases, review API, and report-bot stopped. Volumes are preserved.'
