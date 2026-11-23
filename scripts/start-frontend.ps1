<#
.SYNOPSIS  Start the Vite dev server for the React frontend (Windows).
#>
param(
    [int]$Port = 5173,
    [string]$ApiBaseUrl = "http://localhost:8000/api/v1",
    [switch]$Install
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $frontend "package.json"))) {
    Write-Error "frontend/package.json not found in $frontend"
    exit 1
}
Set-Location $frontend
if ($Install -or -not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    npm install
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$env:VITE_API_BASE_URL = $ApiBaseUrl
Write-Host "Starting frontend on http://localhost:$Port (API: $ApiBaseUrl)"
npm run dev -- --port $Port
exit $LASTEXITCODE
