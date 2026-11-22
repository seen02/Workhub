param([ValidateSet('Apply','Rollback','Reschedule','Improve','Links')][string]$Action = 'Apply')
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskConfig = Join-Path $taskRoot '.local\compose.json'
$taskBackupDir = Join-Path $taskRoot 'backups\deadline-alerts-20261012'
$taskBackupConfig = Join-Path $taskBackupDir 'compose.private.json'
$taskImage = 'unified-work-assistant/workhub:deadline-alerts-20261012'
$taskOriginalImage = 'unified-work-assistant/workhub:report-latency-20261007'
$taskTestsFile = 'reports\deadline-alerts-runtime-tests-20261012.txt'
$taskExpectedTests = 452
if ($Action -eq 'Reschedule' -or ($Action -eq 'Rollback' -and
    (Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json).services.workhub.image -eq 'unified-work-assistant/workhub:deadline-alerts-1715-20261012')) {
    $taskBackupDir = Join-Path $taskRoot 'backups\deadline-alerts-1715-20261012'
    $taskBackupConfig = Join-Path $taskBackupDir 'compose.private.json'
    $taskImage = 'unified-work-assistant/workhub:deadline-alerts-1715-20261012'
    $taskOriginalImage = 'unified-work-assistant/workhub:deadline-alerts-20261012'
    $taskTestsFile = 'reports\deadline-alerts-1715-tests-20261012.txt'
    $taskExpectedTests = 453
}
if ($Action -eq 'Improve' -or ($Action -eq 'Rollback' -and
    (Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json).services.workhub.image -eq 'unified-work-assistant/workhub:deadline-alerts-readable-20261012')) {
    $taskBackupDir = Join-Path $taskRoot 'backups\deadline-alerts-readable-20261012'
    $taskBackupConfig = Join-Path $taskBackupDir 'compose.private.json'
    $taskImage = 'unified-work-assistant/workhub:deadline-alerts-readable-20261012'
    $taskOriginalImage = 'unified-work-assistant/workhub:deadline-alerts-1715-20261012'
    $taskTestsFile = 'reports\deadline-alerts-readable-tests-20261012.txt'
    $taskExpectedTests = 455
}
if ($Action -eq 'Links' -or ($Action -eq 'Rollback' -and
    (Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json).services.workhub.image -eq 'unified-work-assistant/workhub:deadline-alerts-links-20261012')) {
    $taskBackupDir = Join-Path $taskRoot 'backups\deadline-alerts-links-20261012'
    $taskBackupConfig = Join-Path $taskBackupDir 'compose.private.json'
    $taskImage = 'unified-work-assistant/workhub:deadline-alerts-links-20261012'
    $taskOriginalImage = 'unified-work-assistant/workhub:deadline-alerts-readable-20261012'
    $taskTestsFile = 'reports\deadline-alerts-links-tests-20261012.txt'
    $taskExpectedTests = 455
}

function Get-TaskRuntime {
    $taskIds = @(docker compose -f $taskConfig ps -q)
    if ($LASTEXITCODE -ne 0) { throw 'Compose state read failed' }
    $taskRows = docker inspect @taskIds | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Container inspection failed' }
    $taskResult = @{}
    foreach ($taskRow in $taskRows) {
        $taskService = $taskRow.Config.Labels.'com.docker.compose.service'
        $taskResult[$taskService] = [ordered]@{
            id=$taskRow.Id; image=$taskRow.Config.Image; status=$taskRow.State.Status
            health=$taskRow.State.Health.Status
            mounts=@($taskRow.Mounts | Sort-Object Destination | Select-Object Name,Source,Destination,Type)
        }
    }
    return $taskResult
}

Push-Location $taskRoot
try {
    if ($Action -eq 'Rollback') {
        if (-not (Test-Path -LiteralPath $taskBackupConfig)) { throw 'Rollback configuration missing' }
        $taskCurrent = Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
        if ($taskCurrent.services.workhub.image -ne $taskImage) { throw 'Workhub image changed independently' }
        $taskSaved = Get-Content -LiteralPath $taskBackupConfig -Raw | ConvertFrom-Json
        # Keep subsequent unrelated configuration edits.
        $taskCurrent.services.workhub.image = $taskSaved.services.workhub.image
        [IO.File]::WriteAllText($taskConfig, ($taskCurrent | ConvertTo-Json -Depth 100) + "`n", [Text.UTF8Encoding]::new($false))
        docker compose -f $taskConfig up -d --no-deps --no-build --wait --wait-timeout 45 workhub
        if ($LASTEXITCODE -ne 0) { throw 'Rollback restart failed' }
        Write-Output 'Prior local Workhub image restored. Notification preferences and history are preserved.'
        return
    }
    $taskTests = Get-Content -LiteralPath (Join-Path $taskRoot $taskTestsFile) -Raw
    if ($taskTests -notmatch "Ran $taskExpectedTests tests" -or $taskTests.TrimEnd() -notmatch 'OK$') { throw 'Runtime regression gate failed' }
    $taskConfigText = Get-Content -LiteralPath $taskConfig -Raw
    $taskCompose = $taskConfigText | ConvertFrom-Json
    if ($taskCompose.services.workhub.image -ne $taskOriginalImage) { throw 'Workhub image changed independently' }
    $taskBefore = Get-TaskRuntime
    # Historical APPLYING proposals may be pending reconciliation for weeks.
    # The live message worker's PROCESSING state identifies an active chat job.
    $taskBusy = docker exec unified-work-assistant-workhub-1 python -c "from workhub import store;ctx=store.db();c=ctx.__enter__();print(c.execute('SELECT count(*) FROM messages WHERE state=?',('PROCESSING',)).fetchone()[0]);ctx.__exit__(None,None,None)"
    if ($LASTEXITCODE -ne 0 -or [int]$taskBusy -ne 0) { throw 'A user report is in progress; defer restart' }
    New-Item -ItemType Directory -Path $taskBackupDir -Force | Out-Null
    if (Test-Path -LiteralPath $taskBackupConfig) { throw 'Existing rollback snapshot must not be overwritten' }
    [IO.File]::WriteAllText($taskBackupConfig, $taskConfigText, [Text.UTF8Encoding]::new($false))
    $taskBefore | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $taskBackupDir 'runtime-before.json') -Encoding utf8
    docker exec unified-work-assistant-workhub-1 python -c "import sqlite3;from workhub import store;ctx=store.db();c=ctx.__enter__();target=sqlite3.connect('/tmp/deadline-alerts-before.sqlite3');c.backup(target);target.close();ctx.__exit__(None,None,None)"
    if ($LASTEXITCODE -ne 0) { throw 'SQLite backup failed' }
    docker cp unified-work-assistant-workhub-1:/tmp/deadline-alerts-before.sqlite3 (Join-Path $taskBackupDir 'workhub.private.sqlite3')
    if ($LASTEXITCODE -ne 0) { throw 'SQLite backup copy failed' }
    $taskCompose.services.workhub.image = $taskImage
    [IO.File]::WriteAllText($taskConfig, ($taskCompose | ConvertTo-Json -Depth 100) + "`n", [Text.UTF8Encoding]::new($false))
    try {
        docker compose -f $taskConfig up -d --no-deps --no-build --wait --wait-timeout 45 workhub
        if ($LASTEXITCODE -ne 0) { throw 'Local Workhub restart failed' }
        $taskAfter = Get-TaskRuntime
        if ($taskBefore.Count -ne $taskAfter.Count) { throw 'Service count changed' }
        foreach ($taskService in $taskBefore.Keys) {
            $taskOld = $taskBefore[$taskService]; $taskNew = $taskAfter[$taskService]
            if ($taskNew.status -ne 'running' -or $taskNew.health -notin @($null,'healthy')) { throw ('Service health failed: ' + $taskService) }
            if (($taskOld.mounts | ConvertTo-Json -Depth 8 -Compress) -ne ($taskNew.mounts | ConvertTo-Json -Depth 8 -Compress)) { throw ('Mounts changed: ' + $taskService) }
            if ($taskService -ne 'workhub' -and ($taskOld.id -ne $taskNew.id -or $taskOld.image -ne $taskNew.image)) { throw ('Unrelated service changed: ' + $taskService) }
        }
        $taskWritten = Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
        $taskWritten.services.workhub.image = $taskOriginalImage
        if (($taskWritten | ConvertTo-Json -Depth 100 -Compress) -ne (($taskConfigText | ConvertFrom-Json) | ConvertTo-Json -Depth 100 -Compress)) { throw 'Unrelated Compose settings changed' }
        $taskAfterReport = switch ($Action) {
            'Reschedule' { 'reports\deadline-alerts-1715-runtime-after-20261012.json' }
            'Improve' { 'reports\deadline-alerts-readable-runtime-after-20261012.json' }
            'Links' { 'reports\deadline-alerts-links-runtime-after-20261012.json' }
            default { 'reports\deadline-alerts-runtime-after-20261012.json' }
        }
        $taskAfter | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $taskRoot $taskAfterReport) -Encoding utf8
        Write-Output ('Local Workhub updated; ' + $taskAfter.Count + ' services healthy; other containers unchanged.')
    }
    catch {
        [IO.File]::WriteAllText($taskConfig, $taskConfigText, [Text.UTF8Encoding]::new($false))
        docker compose -f $taskConfig up -d --no-deps --no-build --wait --wait-timeout 45 workhub
        throw
    }
}
finally { Pop-Location }
