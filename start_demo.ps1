# One-command demo start: forwards the tablet's localhost:5000 over USB, then runs
# the backend (Adam's FastAPI app in 01/) serving this frontend.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File start_demo.ps1
# Needs the merged repo layout (01/, static/, templates/ side by side) and
# `pip install -r requirements.txt` once.
param(
    [string]$Adb = "$env:USERPROFILE\platform-tools\adb.exe",
    [int]$Port = 5000
)

Set-Location $PSScriptRoot

if (-not (Test-Path "01\app.py")) {
    Write-Host "01\app.py not found next to this script - run it from the merged repo." -ForegroundColor Red
    exit 1
}

if (Test-Path $Adb) {
    $devices = & $Adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" }
    if ($devices) {
        & $Adb reverse "tcp:$Port" "tcp:$Port" | Out-Null
        Write-Host "Tablet connected. Open http://localhost:$Port in Chrome on the tablet." -ForegroundColor Green
    } else {
        Write-Host "No tablet found over USB. Plug it in, allow USB debugging, then re-run this script." -ForegroundColor Yellow
    }
} else {
    Write-Host "adb not found at $Adb - pass -Adb <path>. Starting the server anyway." -ForegroundColor Yellow
}

python -m uvicorn app:app --app-dir 01 --host 127.0.0.1 --port $Port
