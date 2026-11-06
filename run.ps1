# Локальный запуск на Windows: ставит зависимости (при первом запуске), собирает интерфейс и поднимает сервер.
# Откройте http://127.0.0.1:8000 — логин admin / пароль admin.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not (Test-Path "$root\backend\.venv")) {
    python -m venv "$root\backend\.venv"
    & "$root\backend\.venv\Scripts\python" -m pip install -r "$root\backend\requirements.txt"
}
if (-not (Test-Path "$root\frontend\dist\index.html")) {
    Push-Location "$root\frontend"
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
}
Push-Location "$root\backend"
& ".venv\Scripts\python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Pop-Location
