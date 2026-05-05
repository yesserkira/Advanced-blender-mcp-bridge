<#
.SYNOPSIS
    Package the Blender MCP Bridge add-on into a distributable .zip.

.PARAMETER Version
    Semantic version string (e.g. "1.0.0"). If omitted, parsed from
    blender_addon/__init__.py bl_info.

.EXAMPLE
    powershell -NoProfile -File scripts\package_addon.ps1
    powershell -NoProfile -File scripts\package_addon.ps1 -Version 1.0.0
#>
param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$AddonSrc = Join-Path $RepoRoot "blender_addon"
$DistDir = Join-Path $RepoRoot "dist"

# ---------------------------------------------------------------------------
# Resolve version
# ---------------------------------------------------------------------------
if (-not $Version) {
    $InitPy = Join-Path $AddonSrc "__init__.py"
    if (Test-Path -LiteralPath $InitPy) {
        $content = Get-Content -LiteralPath $InitPy -Raw
        if ($content -match '"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)') {
            $Version = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
            Write-Host "Detected version from bl_info: $Version"
        }
    }
    if (-not $Version) {
        $Version = "0.1.0"
        Write-Host "Could not detect version, defaulting to $Version"
    }
}

$ZipName = "blender_mcp_addon_v${Version}.zip"
$ZipPath = Join-Path $DistDir $ZipName

Write-Host ""
Write-Host "=== Blender MCP Add-on Packager ==="
Write-Host "Version : $Version"
Write-Host "Output  : $ZipPath"
Write-Host ""

# ---------------------------------------------------------------------------
# Create temp staging directory
# ---------------------------------------------------------------------------
$StagingBase = Join-Path $env:TEMP "blender_mcp_staging_$(Get-Random)"
$StagingDir = Join-Path $StagingBase "blender_mcp"

if (Test-Path -LiteralPath $StagingBase) {
    Remove-Item -LiteralPath $StagingBase -Recurse -Force
}
New-Item -Path $StagingDir -ItemType Directory -Force | Out-Null

# ---------------------------------------------------------------------------
# Copy add-on files into staging (as "blender_mcp/")
# ---------------------------------------------------------------------------
$IncludeDirs = @("ui", "server", "capabilities", "safety", "vendor")
$IncludeFiles = @("__init__.py", "preferences.py")

foreach ($f in $IncludeFiles) {
    $src = Join-Path $AddonSrc $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $StagingDir $f) -Force
    }
    else {
        Write-Warning "Missing expected file: $f"
    }
}

foreach ($d in $IncludeDirs) {
    $src = Join-Path $AddonSrc $d
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $StagingDir $d) -Recurse -Force
    }
    else {
        Write-Warning "Missing expected directory: $d"
    }
}

# ---------------------------------------------------------------------------
# Remove __pycache__, *.pyc, .pytest_cache, tests/
# ---------------------------------------------------------------------------
Get-ChildItem -LiteralPath $StagingDir -Recurse -Directory -Filter "__pycache__" |
ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

Get-ChildItem -LiteralPath $StagingDir -Recurse -Directory -Filter ".pytest_cache" |
ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

Get-ChildItem -LiteralPath $StagingDir -Recurse -Directory -Filter "tests" |
ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

Get-ChildItem -LiteralPath $StagingDir -Recurse -File -Filter "*.pyc" |
ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

# ---------------------------------------------------------------------------
# Verify vendor/websockets exists
# ---------------------------------------------------------------------------
$VendorWs = Join-Path (Join-Path $StagingDir "vendor") "websockets"
if (-not (Test-Path -LiteralPath $VendorWs)) {
    Write-Warning "vendor/websockets/ not found in staging."
    Write-Warning "Run scripts/vendor_wheels.ps1 first to vendor the websockets wheel."
}

# ---------------------------------------------------------------------------
# Create output zip
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $DistDir)) {
    New-Item -Path $DistDir -ItemType Directory -Force | Out-Null
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

# Compress from the staging base so the zip contains "blender_mcp/" at top level
Compress-Archive -Path $StagingDir -DestinationPath $ZipPath -CompressionLevel Optimal

# ---------------------------------------------------------------------------
# Clean up
# ---------------------------------------------------------------------------
Remove-Item -LiteralPath $StagingBase -Recurse -Force

Write-Host ""
Write-Host "Add-on packaged: $ZipPath"
Write-Host "Install in Blender: Edit > Preferences > Add-ons > Install from Disk"
