param([switch]$Reset)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Reset) { node ops/team_demo.mjs --reset } else { node ops/team_demo.mjs }
if ($LASTEXITCODE -ne 0) { throw '팀 시연 상태 확인에 실패했습니다.' }
