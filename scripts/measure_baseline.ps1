# Phase 0 — baseline measurement.
# Runs the existing pytest suite + extension compile and writes a JSON snapshot
# under scripts/baselines/. Intended to be re-run after each phase to confirm
# no regression.

param(
    [string]$Tag = "v2.0.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $PSScriptRoot "baselines\$Tag.json"
New-Item -ItemType Directory -Path (Split-Path $out) -Force | Out-Null

Write-Host "Running mcp_server pytest..."
$py = Join-Path $root "mcp_server\.venv\Scripts\python.exe"
$pytestRaw = & $py -m pytest -q --tb=no (Join-Path $root "mcp_server") 2>&1
$pytestExit = $LASTEXITCODE
$pytestSummary = ($pytestRaw | Select-Object -Last 3) -join " "
$passed = if ($pytestSummary -match "(\d+) passed") { [int]$Matches[1] } else { 0 }
$failed = if ($pytestSummary -match "(\d+) failed") { [int]$Matches[1] } else { 0 }

Write-Host "Compiling extension..."
Push-Location (Join-Path $root "vscode_extension")
$compileRaw = & npm run compile 2>&1
$compileExit = $LASTEXITCODE
Pop-Location

$payload = [ordered]@{
    tag         = $Tag
    captured_at = (Get-Date).ToString("o")
    pytest      = [ordered]@{
        exit_code = $pytestExit
        passed    = $passed
        failed    = $failed
        summary   = $pytestSummary.Trim()
    }
    extension   = [ordered]@{
        exit_code = $compileExit
        ok        = ($compileExit -eq 0)
    }
}
$payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Host "Wrote $out"
$payload | ConvertTo-Json -Depth 4
