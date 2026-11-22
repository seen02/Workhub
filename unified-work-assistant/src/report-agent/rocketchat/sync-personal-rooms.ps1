$ErrorActionPreference = 'Stop'
$chatRoot = $PSScriptRoot
$projectRoot = Split-Path $chatRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

& $pythonPath (Join-Path $chatRoot 'sync_personal_rooms.py')
if ($LASTEXITCODE -ne 0) { throw 'Personal report room synchronization failed.' }

Write-Host '수동 복구용 개인보고 방 동기화가 완료되었습니다.'
Write-Host '평상시에는 이 스크립트 없이 report-bot이 신규 직원을 최대 약 30초 안에 자동 등록합니다.'
