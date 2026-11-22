param(
    [string]$ImageTag = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [string]$Platform = 'linux/amd64'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$imageNames = @(
    @{ Name = 'custom-outline/outline'; Dockerfile = 'docker/Dockerfile.outline'; Archive = 'outline-image.tar' },
    @{ Name = 'custom-outline/workhub'; Dockerfile = 'docker/Dockerfile.workhub'; Archive = 'workhub-image.tar' }
)

if ($ImageTag -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$') {
    throw "Invalid Docker image tag: $ImageTag"
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
    throw 'Docker CLI was not found. Install/start Docker Desktop and retry.'
}

$engineOs = & docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Engine is unavailable. Start Docker Desktop and retry.'
}
if ($engineOs.Trim() -ne 'linux') {
    throw "Docker Engine must use Linux containers. Current engine: $engineOs"
}

foreach ($image in $imageNames) {
    $dockerfilePath = Join-Path $repoRoot $image.Dockerfile
    if (-not (Test-Path -LiteralPath $dockerfilePath -PathType Leaf)) {
        throw "Dockerfile not found: $dockerfilePath"
    }
}

$references = @($imageNames | ForEach-Object { "$($_.Name):$ImageTag" })
foreach ($reference in $references) {
    & docker image inspect $reference *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "Image tag already exists locally: $reference. Run again with -ImageTag and a new tag."
    }
}

$outputDirectory = Join-Path (Join-Path $repoRoot 'dist/vm-images') $ImageTag
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

foreach ($image in $imageNames) {
    $reference = "$($image.Name):$ImageTag"
    $dockerfilePath = Join-Path $repoRoot $image.Dockerfile
    Write-Host "Building $reference"
    & docker build --platform $Platform --file $dockerfilePath --tag $reference $repoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed: $reference"
    }

    $archivePath = Join-Path $outputDirectory $image.Archive
    Write-Host "Saving $archivePath"
    & docker image save --output $archivePath $reference
    if ($LASTEXITCODE -ne 0) {
        throw "Docker image save failed: $archivePath"
    }
}

$checksumLines = foreach ($image in $imageNames) {
    $archivePath = Join-Path $outputDirectory $image.Archive
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($image.Archive)"
}
$checksumPath = Join-Path $outputDirectory 'images.sha256'
$lineFeed = [string][char]10
$checksumText = ($checksumLines -join $lineFeed) + $lineFeed
[System.IO.File]::WriteAllText($checksumPath, $checksumText, [System.Text.Encoding]::ASCII)

Write-Host ''
Write-Host 'Images are ready for VM transfer:'
Write-Host "  OUTLINE_IMAGE=$($imageNames[0].Name):$ImageTag"
Write-Host "  WORKHUB_IMAGE=$($imageNames[1].Name):$ImageTag"
Write-Host "  $outputDirectory\outline-image.tar"
Write-Host "  $outputDirectory\workhub-image.tar"
Write-Host "  $checksumPath"
Write-Host "  IMAGE_TAG=$ImageTag"
Write-Host "  TARGET_PLATFORM=$Platform"
