# Build a single-file ModelDocker.exe (windowed, no console).
# Run from PowerShell in the repository root:
#   .\build_onefile.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Installing app deps + PyInstaller..." -ForegroundColor Cyan
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt -r requirements-build.txt

$iconPath = Join-Path $PSScriptRoot "ICON.ico"
if (-not (Test-Path $iconPath)) {
    Write-Host "ICON.ico not found at: $iconPath" -ForegroundColor Red
    Write-Host "Place your Windows icon file there as ICON.ico then run this script again." -ForegroundColor Yellow
    exit 1
}
Write-Host "Executable icon: $(Resolve-Path $iconPath)" -ForegroundColor DarkGray

Write-Host "Validating/repairing ICON.ico for PyInstaller..." -ForegroundColor Cyan
python (Join-Path $PSScriptRoot "scripts\normalize_icon.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host "normalize_icon.py failed - fix ICON.ico or install Pillow (pip install pillow)." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Building dist\ModelDocker.exe ..." -ForegroundColor Cyan
python -m PyInstaller --clean --noconfirm ModelDocker.spec

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

$exe = Join-Path $PSScriptRoot "dist\ModelDocker.exe"
if (Test-Path $exe) {
    $len = (Get-Item $exe).Length / 1MB
    Write-Host ('Done: {0} ({1:N1} MB)' -f $exe, $len) -ForegroundColor Green
} else {
    Write-Host "Expected output not found: $exe" -ForegroundColor Red
    exit 1
}
