param([switch]$Reset)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Reset) { node ops/project_demo.mjs --reset } else { node ops/project_demo.mjs }
if ($LASTEXITCODE -ne 0) { throw '프로젝트 시연 상태 확인에 실패했습니다.' }
