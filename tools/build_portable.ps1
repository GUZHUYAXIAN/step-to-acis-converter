param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Resolve-ChildPath([string]$RelativePath) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $repoRoot $RelativePath))
    $prefix = $repoRoot.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path escaped repository root: $candidate"
    }
    return $candidate
}

$buildRoot = Resolve-ChildPath 'build'
$distRoot = Resolve-ChildPath 'dist'
$releaseRoot = Resolve-ChildPath 'release'
$venvRoot = Resolve-ChildPath '.venv-build'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$specPath = Resolve-ChildPath 'packaging\step_to_acis.spec'
$auditTool = Resolve-ChildPath 'tools\audit_release.py'
$appName = 'STEP转ACIS便携版'
$stagingRoot = Join-Path (Join-Path $releaseRoot 'staging') $appName
$zipName = "STEP-to-ACIS-v$Version-windows-x64.zip"
$zipPath = Join-Path $releaseRoot $zipName
$hashPath = "$zipPath.sha256"
$releaseNotes = Resolve-ChildPath "packaging\RELEASE_NOTES_v$Version.md"

if (-not (Test-Path -LiteralPath $releaseNotes -PathType Leaf)) {
    throw "Release notes are missing for version $Version"
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw 'Missing .venv-build. Create it explicitly and install requirements-build.txt first.'
}

$hooksDistribution = 'pyinstaller-hooks-contrib'
$installed = & $venvPython -c "import PyInstaller, _pyinstaller_hooks_contrib; print(PyInstaller.__version__); print(_pyinstaller_hooks_contrib.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read PyInstaller build dependency versions.' }
if ($installed.Count -ne 2 -or $installed[0].Trim() -ne '6.21.0' -or $installed[1].Trim() -ne '2026.6') {
    throw "Build dependency pin mismatch: $($installed -join ', ')"
}

foreach ($target in ($buildRoot, $distRoot, $releaseRoot)) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $releaseRoot | Out-Null

Push-Location $repoRoot
try {
    & $venvPython -m PyInstaller --clean --noconfirm $specPath
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

    $distApp = Join-Path $distRoot $appName
    if (-not (Test-Path -LiteralPath $distApp -PathType Container)) {
        throw "PyInstaller output is missing: $distApp"
    }
    New-Item -ItemType Directory -Path (Split-Path $stagingRoot) | Out-Null
    Copy-Item -LiteralPath $distApp -Destination $stagingRoot -Recurse
    Copy-Item -LiteralPath (Resolve-ChildPath 'packaging\portable_README.md') -Destination (Join-Path $stagingRoot 'README.md')
    Copy-Item -LiteralPath $releaseNotes -Destination (Join-Path $stagingRoot 'RELEASE_NOTES.md')
    Copy-Item -LiteralPath (Resolve-ChildPath 'LICENSE') -Destination (Join-Path $stagingRoot 'LICENSE')
    Copy-Item -LiteralPath (Resolve-ChildPath 'packaging\licenses') -Destination (Join-Path $stagingRoot 'licenses') -Recurse

    & $venvPython -X utf8 $auditTool --staging $stagingRoot --repo-root $repoRoot
    if ($LASTEXITCODE -ne 0) { throw 'Staging audit failed.' }

    Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $hash = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
    "$($hash.Hash.ToUpperInvariant()) *$zipName" | Set-Content -LiteralPath $hashPath -Encoding ascii

    & $venvPython -X utf8 $auditTool --staging $stagingRoot --zip $zipPath --repo-root $repoRoot
    if ($LASTEXITCODE -ne 0) { throw 'ZIP reopen audit failed.' }
}
finally {
    Pop-Location
}

Write-Host "Portable release created: $zipPath"
Write-Host "SHA-256 file created: $hashPath"
