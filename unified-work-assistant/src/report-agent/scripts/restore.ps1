param(
  [Parameter(Mandatory = $true)][string]$BackupPath,
  [string]$DatabaseUrl = $env:DATABASE_URL
)

$ErrorActionPreference = "Stop"
$backup = [System.IO.Path]::GetFullPath($BackupPath)
if (-not (Test-Path -LiteralPath $backup)) { throw "백업 파일을 찾을 수 없습니다: $backup" }
$manifestPath = "$backup.json"
if (Test-Path -LiteralPath $manifestPath) {
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backup).Hash
  if ($actualHash -ne $manifest.sha256) { throw "백업 파일 SHA256 검증에 실패했습니다." }
}

if ([string]::IsNullOrWhiteSpace($DatabaseUrl) -or $DatabaseUrl.StartsWith("sqlite")) {
  $target = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\backend\work_assistant.db"))
  if (Test-Path -LiteralPath $target) {
    $safetyCopy = "$target.pre-restore-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -LiteralPath $target -Destination $safetyCopy
    Write-Output "safety_copy=$safetyCopy"
  }
  Copy-Item -LiteralPath $backup -Destination $target -Force
  Write-Output "restored=$target"
} elseif ($DatabaseUrl.StartsWith("postgresql")) {
  & pg_restore --clean --if-exists --no-owner --dbname=$DatabaseUrl $backup
  if ($LASTEXITCODE -ne 0) { throw "pg_restore가 실패했습니다." }
  Write-Output "restored=postgresql"
} else {
  throw "지원하지 않는 DATABASE_URL입니다."
}
