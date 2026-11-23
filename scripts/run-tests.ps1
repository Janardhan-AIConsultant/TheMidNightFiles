<#
.SYNOPSIS  Run backend (pytest) and optionally frontend (vitest) tests (Windows).
.EXAMPLE   .\scripts\run-tests.ps1 -Frontend
#>
param(
    [switch]$Frontend,
    [string[]]$PytestArgs = @("-q")
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

# Tests never publish for real and use temp databases/dirs.
Write-Host "== Backend tests =="
& $python -m pytest tests @PytestArgs
$backendCode = $LASTEXITCODE

$frontendCode = 0
if ($Frontend) {
    Write-Host "== Frontend tests =="
    Push-Location (Join-Path $root "frontend")
    try {
        npx vitest run
        $frontendCode = $LASTEXITCODE
    } finally { Pop-Location }
}
if ($backendCode -ne 0 -or $frontendCode -ne 0) { exit 1 }
Write-Host "All tests passed."
exit 0
