# start_tracker.ps1 — launch the mobile tracker + public HTTPS tunnel.
#
#   powershell -File tracker\start_tracker.ps1
#
# Requires a one-time token setup (PowerShell):  setx TRACKER_TOKEN "<secret>"
# Coaches enter that token once on the app's setup screen.
#
# The https://....trycloudflare.com URL printed below is a Cloudflare QUICK
# tunnel: free, no account, but the URL CHANGES on every restart — phones must
# visit (and re-install from) the new URL. A permanent URL needs a named
# tunnel + your own domain; do that when coaches start paying.
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent

$token = [Environment]::GetEnvironmentVariable("TRACKER_TOKEN", "User")
if (-not $token) {
    Write-Host "No token set. Run once:  setx TRACKER_TOKEN `"<long-random-secret>`"  then reopen PowerShell." -ForegroundColor Red
    exit 1
}
$env:TRACKER_TOKEN = $token

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
$cfExe = if ($cf) { $cf.Source } else { "C:\Program Files (x86)\cloudflared\cloudflared.exe" }
if (-not (Test-Path $cfExe)) {
    Write-Host "cloudflared not found. Install:  winget install Cloudflare.cloudflared" -ForegroundColor Red
    exit 1
}

$server = Start-Process python `
    -ArgumentList "-m", "uvicorn", "tracker.api:app", "--host", "127.0.0.1", "--port", "8500" `
    -WorkingDirectory $repo -PassThru -WindowStyle Hidden

Write-Host ""
Write-Host "Tracker server running (pid $($server.Id))." -ForegroundColor Green
Write-Host "Coach token: $token" -ForegroundColor Yellow
Write-Host "Tunnel starting - give phones the https://... URL printed below."
Write-Host "Press Ctrl+C to stop both." -ForegroundColor DarkGray
Write-Host ""

try {
    & $cfExe tunnel --url http://localhost:8500
} finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Tracker server stopped."
}
