param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$SpaceClaimExe,

    [ValidateRange(10, 600)]
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Resolve-RepositoryChild([string]$RelativePath) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $repoRoot $RelativePath))
    $prefix = $repoRoot.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Validation path escaped repository root: $candidate"
    }
    return $candidate
}

$validationRoot = Resolve-RepositoryChild ".validation\portable-v$Version"
$releaseRoot = Resolve-RepositoryChild 'release'
$zipPath = Join-Path $releaseRoot "STEP-to-ACIS-v$Version-windows-x64.zip"
$stagingRoot = Join-Path (Join-Path $releaseRoot 'staging') 'STEP转ACIS便携版'
$python = Resolve-RepositoryChild '.venv-build\Scripts\python.exe'
$audit = Resolve-RepositoryChild 'tools\audit_release.py'
$extractionRoot = Join-Path $validationRoot '全新 解压目录'
$stateRoot = Join-Path $validationRoot 'script-self-check-state'
$localAppData = Join-Path $stateRoot 'Local AppData'
$temporaryRoot = Join-Path $stateRoot '临时 空间'
$summaryPath = Join-Path $validationRoot 'script-self-check-summary.txt'

foreach ($required in ($zipPath, $python, $audit, $SpaceClaimExe)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required file is missing: $required"
    }
}

$requestedSpaceClaimPath = (Resolve-Path -LiteralPath $SpaceClaimExe).Path

& $python -X utf8 $audit --staging $stagingRoot --zip $zipPath --repo-root $repoRoot
if ($LASTEXITCODE -ne 0) { throw 'Release audit failed before launch.' }

$validationPrefix = $validationRoot.TrimEnd('\') + '\'
foreach ($target in ($extractionRoot, $stateRoot)) {
    $resolved = [IO.Path]::GetFullPath($target)
    if (-not $resolved.StartsWith($validationPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe validation cleanup target: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolved | Out-Null
}
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractionRoot
New-Item -ItemType Directory -Path $localAppData, $temporaryRoot | Out-Null

$application = Join-Path $extractionRoot 'STEP转ACIS.exe'
$spaceClaimRoot = Split-Path (Split-Path $requestedSpaceClaimPath)
$oldLocalAppData = $env:LOCALAPPDATA
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$oldAwpRoot = $env:AWP_ROOT222
$process = $null
try {
    $env:LOCALAPPDATA = $localAppData
    $env:TEMP = $temporaryRoot
    $env:TMP = $temporaryRoot
    $env:AWP_ROOT222 = $spaceClaimRoot
    $process = Start-Process -FilePath $application -WorkingDirectory $extractionRoot -PassThru
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $cacheRoot = Join-Path $localAppData 'SpaceClaimStepToAcis\environment\capability_profiles'
    do {
        Start-Sleep -Milliseconds 500
        $caches = @(Get-ChildItem -LiteralPath $cacheRoot -Filter '*.json' -ErrorAction SilentlyContinue)
        if ($caches.Count -gt 0) { break }
        if ($process.HasExited) { throw "Packaged EXE exited early: $($process.ExitCode)" }
    } while ((Get-Date) -lt $deadline)
    if ($caches.Count -ne 1) { throw "Expected one capability cache, found $($caches.Count)." }

    $cache = Get-Content -LiteralPath $caches[0].FullName -Raw | ConvertFrom-Json
    $cachedSpaceClaimPath = [IO.Path]::GetFullPath([string]$cache.identity.absolute_path)
    if (-not [string]::Equals($cachedSpaceClaimPath, $requestedSpaceClaimPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "SpaceClaim identity path mismatch: requested=$requestedSpaceClaimPath cached=$cachedSpaceClaimPath"
    }
    $requestedSpaceClaimHash = (Get-FileHash -LiteralPath $requestedSpaceClaimPath -Algorithm SHA256).Hash.ToUpperInvariant()
    if (-not [string]::Equals($requestedSpaceClaimHash, [string]$cache.identity.sha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw "SpaceClaim identity SHA-256 mismatch for: $requestedSpaceClaimPath"
    }
    $report = Get-Content -LiteralPath $cache.probe_report -Raw | ConvertFrom-Json
    if ($report.required_stages_passed -ne $true) { throw 'Required Headless self-check failed.' }
    $forbidden = @(Get-ChildItem -LiteralPath (Join-Path $localAppData 'SpaceClaimStepToAcis') -File -Recurse | Where-Object {
        $_.Extension.ToLowerInvariant() -in @('.stp', '.step', '.sab', '.sat')
    })
    if ($forbidden.Count -gt 0) { throw 'Model or ACIS files appeared during model-free self-check.' }

    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToUpperInvariant()
    $lines = @(
        "version=$Version",
        "zip=$zipPath",
        "zip_bytes=$((Get-Item -LiteralPath $zipPath).Length)",
        "zip_sha256=$hash",
        "extraction=$extractionRoot",
        "executable=$application",
        "spaceclaim=$($cache.identity.absolute_path)",
        "spaceclaim_sha256=$($cache.identity.sha256)",
        "probe_report=$($cache.probe_report)",
        "required_stages_passed=$($report.required_stages_passed)",
        "probe_stages=$(($report.stages.name) -join ',')",
        'model_files_created=0'
    )
    [IO.File]::WriteAllLines($summaryPath, $lines, [Text.UTF8Encoding]::new($true))
    Write-Host "PACKAGED MODEL-FREE SELF-CHECK PASSED"
    Write-Host "Evidence: $summaryPath"
}
finally {
    $env:LOCALAPPDATA = $oldLocalAppData
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    $env:AWP_ROOT222 = $oldAwpRoot
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}
