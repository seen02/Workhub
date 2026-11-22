param([switch]$LegacyReport)
$ErrorActionPreference = 'Stop'
$composePath = Join-Path $PSScriptRoot 'compose.yml'
$composeArgs = @('compose','-f',$composePath)
if ($LegacyReport) { $composeArgs += @('--profile','legacy-report') }
& docker @composeArgs up -d --no-build
if ($LASTEXITCODE -ne 0) { throw 'Unified project startup failed.' }
