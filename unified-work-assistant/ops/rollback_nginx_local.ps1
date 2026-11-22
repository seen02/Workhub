param([string]$Python='python')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
Push-Location $root
try {
  # Restore persistent SSO settings while the current public endpoints still work.
  & $Python ops/nginx_transition.py restore-settings
  if($LASTEXITCODE -ne 0){throw 'SSO restoration failed; compose has not been changed.'}
  Copy-Item -LiteralPath '.local/nginx-transition/before-compose.json' -Destination '.local/compose.json'
  Copy-Item -LiteralPath '.local/nginx-transition/before-integration.json' -Destination '.local/integration.json'
  docker compose up -d --no-build
  if($LASTEXITCODE -ne 0){throw 'Container restoration failed; review docker compose ps.'}
  Write-Output 'Original service URLs restored. To remove the optional test hostnames, run ops/set_nginx_test_hosts.ps1 -Mode Remove as Administrator.'
} finally { Pop-Location }
