param(
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\backups")
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

if ([string]::IsNullOrWhiteSpace($DatabaseUrl) -or $DatabaseUrl.StartsWith("sqlite")) {
  $source = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\backend\work_assistant.db"))
  if (-not (Test-Path -LiteralPath $source)) { throw "SQLite DB를 찾을 수 없습니다: $source" }
  $target = [System.IO.Path]::GetFullPath((Join-Path $OutputDirectory "work_assistant-$stamp.db"))
  Copy-Item -LiteralPath $source -Destination $target
} elseif ($DatabaseUrl.StartsWith("postgresql")) {
  $target = [System.IO.Path]::GetFullPath((Join-Path $OutputDirectory "work_assistant-$stamp.dump"))
  & pg_dump --format=custom --file=$target $DatabaseUrl
  if ($LASTEXITCODE -ne 0) { throw "pg_dump가 실패했습니다." }
} else {
  throw "지원하지 않는 DATABASE_URL입니다."
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
$manifestPath = "$target.json"
@{ created_at = (Get-Date).ToString("o"); file = (Split-Path $target -Leaf); sha256 = $hash } | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output "backup=$target"
Write-Output "sha256=$hash"
