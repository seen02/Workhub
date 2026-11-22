param([switch]$Reset)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Reset) { node ops/reset_demo.mjs } else { node ops/seed_demo.mjs }
if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed' }
Write-Output '시연 시작: http://localhost:8004'
Write-Output '생성된 업무 정보: reports/demo-manifest.json'
