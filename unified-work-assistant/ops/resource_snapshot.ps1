param([string]$Label='current')
$ErrorActionPreference='Stop'
$destination=Join-Path (Split-Path $PSScriptRoot -Parent) "reports/resources-$Label.txt"
@(
  "Captured: $(Get-Date -Format o)"
  docker stats --no-stream --format '{{.Name}} | {{.MemUsage}} | {{.CPUPerc}}'
  wsl -d docker-desktop -- cat /proc/meminfo
  Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | Format-List | Out-String
  nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader
  Get-PSDrive -Name C | Select-Object Used,Free | Format-List | Out-String
) | Set-Content -LiteralPath $destination -Encoding utf8
Get-Content -LiteralPath $destination
