$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Single source of truth for the version: VERSION in src/pdf_editor/__init__.py
$VersionMatch = Select-String -Path "src\pdf_editor\__init__.py" -Pattern '^VERSION = "(\d+\.\d+\.\d+)"'
if (-not $VersionMatch) { throw "VERSION not found in src\pdf_editor\__init__.py" }
$Version = $VersionMatch.Matches[0].Groups[1].Value
if (-not (Select-String -Path "assets\version_info.txt" -SimpleMatch "'FileVersion', '$Version.0'" -Quiet)) {
    throw "assets\version_info.txt does not match VERSION $Version"
}
Write-Host "Building PdfEditor $Version" -ForegroundColor Cyan

Write-Host "1/3 Generating application icon..." -ForegroundColor Cyan
python assets\generate_icon.py

Write-Host "2/3 Running full test suite..." -ForegroundColor Cyan
& "$Root\scripts\test.ps1"

Write-Host "3/3 Building single distributable installer..." -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --noconsole `
    --name PdfEditor `
    --icon assets\app.ico `
    --version-file assets\version_info.txt `
    --add-data "assets\app.ico;assets" `
    --add-data "locales;locales" `
    --paths src `
    --hidden-import win32com.client `
    --hidden-import pythoncom `
    --exclude-module tkinter `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtWebEngineQuick `
    --exclude-module PySide6.QtWebChannel `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.Qt3DRender `
    --exclude-module PySide6.Qt3DInput `
    --exclude-module PySide6.Qt3DLogic `
    --exclude-module PySide6.Qt3DAnimation `
    --exclude-module PySide6.Qt3DExtras `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQuickWidgets `
    --exclude-module PySide6.QtMultimedia `
    --exclude-module PySide6.QtMultimediaWidgets `
    --exclude-module PySide6.QtNetwork `
    --exclude-module PySide6.QtSql `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtPdfWidgets `
    --exclude-module PySide6.QtSvg `
    --exclude-module PySide6.QtCharts `
    --exclude-module PySide6.QtDataVisualization `
    --exclude-module PySide6.QtOpenGL `
    --exclude-module PySide6.QtOpenGLWidgets `
    --exclude-module numpy `
    --exclude-module lxml `
    --exclude-module pandas `
    --exclude-module matplotlib `
    --exclude-module scipy `
    --exclude-module pygame `
    run_app.py

$ExePath = Join-Path $Root "dist\PdfEditor.exe"
$SetupPath = Join-Path $Root "dist\PdfEditor_Setup_v$Version.exe"
if (Test-Path $ExePath) {
    Copy-Item -Force $ExePath $SetupPath
    $Hash = (Get-FileHash -Algorithm SHA256 $SetupPath).Hash.ToLowerInvariant()
    "$Hash  PdfEditor_Setup_v$Version.exe" | Out-File -Encoding ascii "$SetupPath.sha256"
    $SizeMB = [math]::Round((Get-Item $SetupPath).Length / 1MB, 2)
    Write-Host "`nDone! Distributable installer: $SetupPath ($SizeMB MB)" -ForegroundColor Green
    Write-Host "SHA-256: $Hash" -ForegroundColor Green
} else {
    throw "Build failed: $ExePath was not created."
}
