# scripts/vendor_wheels.ps1
# Downloads websockets==12.0 pure-Python wheel from PyPI and extracts it into blender_addon/vendor/
# No pip required — downloads directly from PyPI via HTTPS.

$ErrorActionPreference = "Stop"
$VendorDir = Join-Path $PSScriptRoot "..\blender_addon\vendor"
$TempDir = Join-Path $VendorDir "_temp"
$WheelUrl = "https://files.pythonhosted.org/packages/79/4d/9cc401e7b07e80532ebc8c8e993f42541534da9e9249c59ee0139dcb0352/websockets-12.0-py3-none-any.whl"
$WheelHash = "B1A29E856655D8E5DF8C4E5E68B1F4E3E4F3D6E21B5A5F0DFEEB5B6E7C2D1A0" # placeholder, verify after download

# Clean previous vendor
if (Test-Path (Join-Path $VendorDir "websockets")) {
    Remove-Item -Recurse -Force (Join-Path $VendorDir "websockets")
}
if (Test-Path $TempDir) {
    Remove-Item -Recurse -Force $TempDir
}

New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

$WheelPath = Join-Path $TempDir "websockets-12.0-py3-none-any.whl"

Write-Host "Downloading websockets==12.0 from PyPI..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $WheelUrl -OutFile $WheelPath -UseBasicParsing

if (-not (Test-Path $WheelPath)) {
    Write-Error "Download failed"
    exit 1
}

Write-Host "Extracting wheel..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($WheelPath, $TempDir)

# Move websockets package to vendor/
$src = Join-Path $TempDir "websockets"
$dst = Join-Path $VendorDir "websockets"
if (Test-Path $src) {
    Move-Item -Path $src -Destination $dst
}
else {
    Write-Error "websockets directory not found after extraction"
    exit 1
}

# Clean up temp
Remove-Item -Recurse -Force $TempDir

Write-Host "websockets vendored at $dst"
Write-Host "Done."
