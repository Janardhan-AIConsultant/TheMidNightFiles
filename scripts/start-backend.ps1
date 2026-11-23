<#
.SYNOPSIS  Start the Midnight Files FastAPI backend (Windows).
.EXAMPLE   .\scripts\start-backend.ps1 -Port 8000 -NoReload
#>
param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1",
    [switch]$NoReload
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

if (-not (Test-Path (Join-Path $root ".env"))) {
    Write-Warning ".env not found - using defaults/environment variables. Copy .env.example to .env and set secrets."
}
foreach ($d in "data", "data\content", "data\cache", "logs") {
    New-Item -ItemType Directory -Force -Path (Join-Path $root $d) | Out-Null
}

$uvicornArgs = @("-m", "uvicorn", "backend.main:app", "--host", $BindHost, "--port", $Port)
if (-not $NoReload) { $uvicornArgs += "--reload" }
Write-Host "Starting backend on http://${BindHost}:$Port (docs: /docs, API: /api/v1)"
& $python @uvicornArgs
exit $LASTEXITCODE
