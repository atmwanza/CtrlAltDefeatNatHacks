# One-command demo start: makes the tablet's localhost:<Port> reach this laptop, then
# runs the backend (Adam's FastAPI app in 01/) serving this frontend.
#
#   USB:       powershell -ExecutionPolicy Bypass -File start_demo.ps1
#   Wireless:  powershell -ExecutionPolicy Bypass -File start_demo.ps1 -Wireless
#
# Wireless needs the laptop and tablet on a network you control (laptop Mobile Hotspot
# or a phone hotspot). Venue/university Wi-Fi such as eduroam blocks devices from
# reaching each other. With -Wireless:
#   - tablet plugged in by USB: switches adb to Wi-Fi, connects, then you can unplug;
#   - tablet not plugged in: reconnects to the last tablet (adb's Wi-Fi mode lasts until
#     the tablet restarts), or to -TabletIp.
# Either way the tablet still opens http://localhost:<Port>: adb forwards it, which keeps
# the page a secure context so Chrome gives the full-rate pen data.
#
# Finger-tapping camera (prototype):
#   -Pi       let the Raspberry Pi reach the backend (listens on all interfaces; run
#             tools\setup_firewall.ps1 once as Administrator so only the hotspot and the
#             Ethernet fallback can connect)
#   -Webcam   use the laptop webcam instead of the Pi (fallback, and for testing)
#
# Needs the merged repo layout (01/, static/, templates/ side by side) and
# `pip install -r requirements.txt` once.
param(
    [string]$Adb = "$env:USERPROFILE\platform-tools\adb.exe",
    [int]$Port = 5000,
    [switch]$Wireless,
    [string]$TabletIp = "",
    [switch]$Pi,
    [switch]$Webcam
)

Set-Location $PSScriptRoot
$AdbTcpPort = 5555
$LastIpFile = Join-Path $env:TEMP "drawdx_tablet_ip.txt"

if (-not (Test-Path "01\app.py")) {
    Write-Host "01\app.py not found next to this script - run it from the merged repo." -ForegroundColor Red
    exit 1
}

function Get-AdbDevices {
    # serials of attached devices in the "device" state
    & $Adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" } |
        ForEach-Object { ($_ -split "\t")[0] }
}

function Connect-WirelessTablet {
    $usb = Get-AdbDevices | Where-Object { $_ -notmatch ":" } | Select-Object -First 1
    $ip = $TabletIp
    if ($usb) {
        $line = & $Adb -s $usb shell ip -f inet addr show wlan0 | Select-String "inet "
        if (-not $line) {
            Write-Host "The tablet isn't on Wi-Fi. Connect it to the hotspot, then re-run." -ForegroundColor Red
            return $null
        }
        $ip = ($line.ToString().Trim() -split "\s+")[1].Split("/")[0]
        & $Adb -s $usb tcpip $AdbTcpPort | Out-Null
        Start-Sleep -Seconds 3
    }
    if (-not $ip -and (Test-Path $LastIpFile)) { $ip = (Get-Content $LastIpFile -Raw).Trim() }
    if (-not $ip) {
        Write-Host "No tablet IP. Plug the tablet in by USB once, or pass -TabletIp <ip>." -ForegroundColor Red
        return $null
    }
    $target = if ($ip -match ":") { $ip } else { "${ip}:$AdbTcpPort" }
    $out = & $Adb connect $target 2>&1 | Out-String
    if ($out -notmatch "connected to") {
        Write-Host "Could not reach the tablet at $target ($($out.Trim()))." -ForegroundColor Red
        Write-Host "Check both are on the same hotspot (not eduroam). If the tablet restarted, plug it in by USB once and re-run." -ForegroundColor Yellow
        return $null
    }
    Set-Content -Path $LastIpFile -Value $ip
    if ($usb) { Write-Host "Connected over Wi-Fi ($target). You can unplug the USB cable now." -ForegroundColor Green }
    return $target
}

if (-not (Test-Path $Adb)) {
    Write-Host "adb not found at $Adb - pass -Adb <path>. Starting the server anyway." -ForegroundColor Yellow
} elseif ($Wireless) {
    $serial = Connect-WirelessTablet
    if ($serial) {
        & $Adb -s $serial reverse "tcp:$Port" "tcp:$Port" | Out-Null
        Write-Host "Tablet connected wirelessly. Open http://localhost:$Port in Chrome on the tablet." -ForegroundColor Green
        # Wi-Fi adb can drop (tablet sleeps, hotspot blips); the forward goes with it.
        # Re-check every 10 s and restore both, so the demo heals itself.
        $watchLog = Join-Path $env:TEMP "drawdx_tablet_watchdog.log"
        Write-Host "Tablet watchdog log: $watchLog" -ForegroundColor DarkGray
        Start-Job -ArgumentList $Adb, $serial, $Port, $watchLog -ScriptBlock {
            param($adb, $serial, $port, $log)
            $fails = 0
            while ($true) {
                Start-Sleep -Seconds 10
                $state = (& $adb -s $serial get-state 2>&1 | Out-String).Trim()
                if ($state -ne "device") {
                    # "offline" means adb still lists a dead link and `connect` replies "already
                    # connected", so drop it first, then reconnect
                    & $adb disconnect $serial 2>&1 | Out-Null
                    & $adb connect $serial 2>&1 | Out-Null
                    $state = (& $adb -s $serial get-state 2>&1 | Out-String).Trim()
                    if ($state -ne "device") { $fails = 0; continue }   # tablet asleep or off the hotspot
                    Add-Content -Path $log -Value "$(Get-Date -Format T) reconnected"
                }
                $fwd = & $adb -s $serial reverse --list 2>&1 | Out-String
                if ($fwd -notmatch "tcp:$port") { & $adb -s $serial reverse "tcp:$port" "tcp:$port" 2>&1 | Out-Null }
                # After a Wi-Fi blip the forward can stay listed but carry nothing (the tablet then
                # can't open localhost). Send a real request through it from the tablet; after two
                # failed checks in a row, restart adb and rebuild the link.
                $probe = & $adb -s $serial shell "(printf 'GET /health HTTP/1.0\r\n\r\n'; sleep 2) | nc 127.0.0.1 $port | head -1" 2>&1 | Out-String
                if ($probe -match "200 OK") { $fails = 0; continue }
                $fails++
                if ($fails -lt 2) { continue }
                & $adb kill-server 2>&1 | Out-Null
                & $adb connect $serial 2>&1 | Out-Null
                Start-Sleep -Seconds 2
                & $adb -s $serial reverse "tcp:$port" "tcp:$port" 2>&1 | Out-Null
                Add-Content -Path $log -Value "$(Get-Date -Format T) tunnel was stuck: restarted adb and rebuilt it"
                $fails = 0
            }
        } | Out-Null
    }
} else {
    $usb = Get-AdbDevices | Where-Object { $_ -notmatch ":" } | Select-Object -First 1
    if ($usb) {
        & $Adb -s $usb reverse "tcp:$Port" "tcp:$Port" | Out-Null
        Write-Host "Tablet connected. Open http://localhost:$Port in Chrome on the tablet." -ForegroundColor Green
    } else {
        Write-Host "No tablet found over USB. Plug it in, allow USB debugging, then re-run this script (or use -Wireless)." -ForegroundColor Yellow
    }
}

$BindHost = "127.0.0.1"
if ($Pi) {
    $BindHost = "0.0.0.0"
    Write-Host "Pi mode: backend reachable from the hotspot (192.168.137.x) and Ethernet (10.42.0.x)." -ForegroundColor Green
    Write-Host "  The Pi should appear in the Tapping tab within ~10 s of booting." -ForegroundColor Green
}

$capture = $null
if ($Webcam) {
    # same capture service the Pi runs, using the laptop webcam; it finds the backend on localhost
    $env:SOURCE = "webcam"
    $capture = Start-Process -FilePath python -ArgumentList "pi\pi_capture.py" -NoNewWindow -PassThru
    Remove-Item Env:SOURCE
    Write-Host "Webcam capture started (Tapping tab should show 'laptop webcam connected')." -ForegroundColor Green
}

try {
    python -m uvicorn server:app --app-dir 01 --host $BindHost --port $Port
} finally {
    if ($capture -and -not $capture.HasExited) { Stop-Process -Id $capture.Id -Force }
    Get-Job | Stop-Job -PassThru | Remove-Job
}
