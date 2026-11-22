param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$pythonCommand = Get-Command python -ErrorAction Stop
& $pythonCommand.Source (Join-Path $PSScriptRoot 'manage.py') @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Deployment operation failed. Check the message above.' }
