# One-time: allow the Raspberry Pi to reach the PRISM backend on this laptop.
# Run in PowerShell **as Administrator**:
#     powershell -ExecutionPolicy Bypass -File tools\setup_firewall.ps1
#
# Opens TCP 5000 only to the laptop hotspot (192.168.137.0/24) and the direct-Ethernet
# fallback (10.42.0.0/24), so nothing on eduroam or other networks can connect.
param([int]$Port = 5000)

$name = "DrawDx: Pi -> backend $Port"
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -RemoteAddress 192.168.137.0/24,10.42.0.0/24 -Profile Any | Out-Null
Write-Host "Added firewall rule '$name'." -ForegroundColor Green

# Dismissing Windows' "allow Python?" pop-up can leave Block rules, which beat Allow rules.
$blocks = Get-NetFirewallRule -Direction Inbound -Action Block -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "*ython*" }
if ($blocks) {
    Write-Host "Found inbound Block rules for Python that would stop the Pi:" -ForegroundColor Yellow
    $blocks | Format-Table DisplayName, Profile -AutoSize | Out-String | Write-Host
    $answer = Read-Host "Remove them? (y/n)"
    if ($answer -eq "y") { $blocks | Remove-NetFirewallRule; Write-Host "Removed." -ForegroundColor Green }
}
