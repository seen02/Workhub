$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$target = Join-Path $PSScriptRoot "backups\integrated-$stamp"
New-Item -ItemType Directory -Path $target | Out-Null
$jobs = @(
  @{Container='unified-work-assistant-postgres-1'; User='outline'; Database='outline'; Name='outline.dump'},
  @{Container='unified-work-assistant-postgresql-1'; User='authentik'; Database='authentik'; Name='authentik.dump'}
)
foreach ($job in $jobs) {
  docker exec $job.Container pg_dump -U $job.User -d $job.Database -Fc -f /tmp/integrated-backup.dump
  if ($LASTEXITCODE -ne 0) { throw "DB backup failed: $($job.Database)" }
  docker cp "$($job.Container):/tmp/integrated-backup.dump" (Join-Path $target $job.Name)
  if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed' }
}
docker exec unified-work-assistant-workhub-1 python -c "import sqlite3; source=sqlite3.connect('/app/data/workhub.sqlite3'); destination=sqlite3.connect('/app/data/backup.sqlite3'); source.backup(destination); destination.close()"
if ($LASTEXITCODE -ne 0) { throw 'Workhub backup failed' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'runtime\workhub\backup.sqlite3') -Destination (Join-Path $target 'workhub.sqlite3')
docker exec unified-work-assistant-open-webui-1 python -c "import sqlite3; s=sqlite3.connect('/app/backend/data/webui.db'); d=sqlite3.connect('/tmp/webui-backup.db'); s.backup(d); d.close()"
docker cp unified-work-assistant-open-webui-1:/tmp/webui-backup.db (Join-Path $target 'webui.db')
docker exec unified-work-assistant-mongodb-1 mongodump --db rocketchat --archive=/tmp/rocketchat-backup.archive --gzip
if ($LASTEXITCODE -ne 0) { throw 'Rocket.Chat backup failed' }
docker cp unified-work-assistant-mongodb-1:/tmp/rocketchat-backup.archive (Join-Path $target 'rocketchat.archive.gz')
docker exec unified-work-assistant-outline-1 tar -czf /tmp/outline-files.tar.gz -C /var/lib/outline/data .
if ($LASTEXITCODE -ne 0) { throw 'Outline attachment backup failed' }
docker cp unified-work-assistant-outline-1:/tmp/outline-files.tar.gz (Join-Path $target 'outline-files.tar.gz')
docker exec unified-work-assistant-document-agent-1 python -c "import sqlite3; from pathlib import Path; root=Path('/app/data'); [(lambda s,d: (s.backup(d),d.close(),s.close()))(sqlite3.connect(p),sqlite3.connect('/tmp/'+p.name)) for p in root.glob('*.sqlite3')]"
if ($LASTEXITCODE -ne 0) { throw 'Document agent database backup failed' }
docker cp unified-work-assistant-document-agent-1:/tmp/agent.sqlite3 (Join-Path $target 'document-agent.sqlite3')
docker cp unified-work-assistant-document-agent-1:/tmp/jobs.sqlite3 (Join-Path $target 'document-jobs.sqlite3')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'runtime\authentik') -Destination (Join-Path $target 'authentik-files') -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'runtime\document-agent\uploads') -Destination (Join-Path $target 'document-uploads') -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.local\compose.json') -Destination (Join-Path $target 'compose.private.json')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.local\integration.json') -Destination (Join-Path $target 'integration.private.json')
Get-ChildItem -LiteralPath $target -File | Get-FileHash -Algorithm SHA256 | Select-Object Path,Hash | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'checksums.json') -Encoding utf8
Write-Output "데이터베이스·설정 백업 완료: $target"
foreach ($name in @('outline.dump','authentik.dump','workhub.sqlite3','webui.db','rocketchat.archive.gz','outline-files.tar.gz','document-agent.sqlite3','document-jobs.sqlite3')) {
  if (-not (Test-Path -LiteralPath (Join-Path $target $name))) { throw "Missing backup: $name" }
}
Write-Output 'Outline 첨부·문서 비서 기록을 포함했습니다. 모델·RAG 색인은 기존 볼륨에 보존합니다. 이 백업의 인증 설정은 비공개로 관리하세요.'
