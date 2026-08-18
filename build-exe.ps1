$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    python -m pip install -r "requirements-release.txt"
    python -m pip install -e . --no-deps
    python -m pytest
    python -m ruff check .
    python -m ruff format --check .
    python -m PyInstaller --clean --noconfirm "OpenOCD-Scope.spec"
    Write-Host "Build complete: $projectRoot\dist\OpenOCD-Scope.exe"
}
finally {
    Pop-Location
}
