param([ValidateSet('Install','Remove')][string]$Mode='Install')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
$status=Join-Path $root '.local/nginx-transition/hosts-status.json'
try {
  $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator access is required for the Windows hosts file.'}
  $hostsPath=Join-Path $env:SystemRoot 'System32/drivers/etc/hosts'
  $text=[IO.File]::ReadAllText($hostsPath)
  $begin='# BEGIN WORKHUB NGINX TEST'; $end='# END WORKHUB NGINX TEST'
  $pattern='(?ms)^'+[regex]::Escape($begin)+'\r?\n.*?^'+[regex]::Escape($end)+'\r?\n?'
  $clean=[regex]::Replace($text,$pattern,'')
  if($Mode -eq 'Install'){
    $names=@('workhub.test','rocketchat.workhub.test','outline.workhub.test','ai.workhub.test','authentik.workhub.test')
    foreach($name in $names){
      foreach($line in ($clean -split '\r?\n')){if(($line -split '#')[0] -match ('(?:^|\s)'+[regex]::Escape($name)+'(?:\s|$)')){throw "A hosts entry already exists for $name"}}
    }
    $backup=Join-Path $root '.local/nginx-transition/hosts-before.txt'
    if(-not (Test-Path -LiteralPath $backup)){[IO.File]::WriteAllText($backup,$text)}
    $clean=$clean.TrimEnd()+"`r`n`r`n"+$begin+"`r`n"+(($names | ForEach-Object {'127.0.0.1 '+$_}) -join "`r`n")+"`r`n"+$end+"`r`n"
  }
  [IO.File]::WriteAllText($hostsPath,$clean,[Text.UTF8Encoding]::new($false))
  Clear-DnsClientCache
  @{ok=$true;mode=$Mode;at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding utf8
} catch {
  @{ok=$false;mode=$Mode;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding utf8
  exit 1
}
