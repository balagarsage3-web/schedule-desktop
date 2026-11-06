$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    & 'backend/.venv/Scripts/python.exe' -m PyInstaller --noconfirm desktop/Schedule.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    & 'installer/tools/Inno/ISCC.exe' 'installer/Schedule.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
} finally { Pop-Location }
