param([string]$SqliteSource = "")

$ErrorActionPreference = 'Stop'
$chatRoot = $PSScriptRoot
$projectRoot = Split-Path $chatRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$localPath = Join-Path $chatRoot '.local'
$composePath = Join-Path $chatRoot 'compose.yml'
$composeEnv = Join-Path $localPath 'compose.env'

& $pythonPath (Join-Path $chatRoot 'setup.py') init
if ($LASTEXITCODE -ne 0) { throw 'Credential initialization failed.' }

docker compose --env-file $composeEnv -f $composePath up -d reportdb mongodb rocketchat
if ($LASTEXITCODE -ne 0) { throw 'Rocket.Chat and databases failed to start. Check Docker Desktop.' }

$databaseReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    docker compose --env-file $composeEnv -f $composePath exec -T reportdb `
        pg_isready -U work_agent -d work_agent *> $null
    if ($LASTEXITCODE -eq 0) { $databaseReady = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $databaseReady) { throw 'PostgreSQL report database is still starting.' }

$chatReady = $false
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $result = Invoke-RestMethod 'http://127.0.0.1:3000/api/info' -TimeoutSec 3
        if ($result.success) { $chatReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $chatReady) { throw 'Rocket.Chat is still starting. Retry this script later.' }

& $pythonPath (Join-Path $chatRoot 'setup.py') provision
if ($LASTEXITCODE -ne 0) { throw 'Test account provisioning failed.' }
& $pythonPath (Join-Path $chatRoot 'provision_team.py')
if ($LASTEXITCODE -ne 0) { throw 'Technical support team provisioning failed.' }

$backupPath = Join-Path $projectRoot 'backups'
New-Item -ItemType Directory -Force -Path $backupPath | Out-Null
if ([string]::IsNullOrWhiteSpace($SqliteSource)) {
    $candidate = Join-Path $projectRoot 'backend\work_assistant.db'
    if (Test-Path -LiteralPath $candidate) { $SqliteSource = $candidate }
}

$migrationArgs = @('compose', '--env-file', $composeEnv, '-f', $composePath, 'run', '--rm', '--no-deps')
$migrationArgs += @('-e', 'MIGRATION_BACKUP_PATH=/migration-backup', '-v', "${backupPath}:/migration-backup")
if (-not [string]::IsNullOrWhiteSpace($SqliteSource)) {
    $resolvedSource = [System.IO.Path]::GetFullPath($SqliteSource)
    if (-not (Test-Path -LiteralPath $resolvedSource -PathType Leaf)) {
        throw "SQLite source not found: $resolvedSource"
    }
    $migrationArgs += @('-e', 'SQLITE_SOURCE_PATH=/migration-source/work_assistant.db', `
                        '-v', "${resolvedSource}:/migration-source/work_assistant.db:ro")
}
$migrationArgs += @('review', 'python', 'migrate_to_postgres.py')
& docker @migrationArgs
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL schema or SQLite data migration failed.' }

docker compose --env-file $composeEnv -f $composePath up -d --build review worker
if ($LASTEXITCODE -ne 0) { throw 'Containerized review API or report bot failed to start.' }

$workspaceConfig = Get-Content -Raw -LiteralPath (Join-Path $localPath 'bot.json') | ConvertFrom-Json
$personalChatUrl = 'http://127.0.0.1:3000/group/' + $workspaceConfig.personal_rooms.'poc-employee'.name
Write-Host "Personal report room: $personalChatUrl"
Write-Host 'Report review: http://127.0.0.1:8003'
Write-Host 'Guide: http://127.0.0.1:8003/assets/team-guide.html'
Write-Host 'Login: rocketchat/.local/LOGIN.txt'
Write-Host 'Rocket.Chat, PostgreSQL, review API, and report-bot are running in Docker.'
