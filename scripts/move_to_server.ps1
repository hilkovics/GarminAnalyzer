<#
.SYNOPSIS
  Move the app from this Windows PC to the always-on home server (docs/SERVER.md, step 4).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\move_to_server.ps1 -Server samuel@trening
  powershell -ExecutionPolicy Bypass -File scripts\move_to_server.ps1 -Server samuel@trening -Url https://trening.tail1234.ts.net

.NOTES
  What it does, in this order:
  1. stops the local app server (if it runs) and folds the SQLite WAL into data\training.db;
  2. copies data\training.db and the Garmin tokens (%USERPROFILE%\.garminconnect\garmin_tokens.json) to the
     server with scp (Windows' built-in OpenSSH; you type the server password, nothing is stored);
  3. removes the Windows morning task – from now on only the server syncs and pushes to Garmin
     (two machines with two databases would push every workout twice);
  4. with -Url: points the desktop icon at the server's address.
  Run it BEFORE scripts/server_setup.sh on the server, or stop the server's containers first (docker compose down).
#>
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$RemoteDir = "GarminAnalyzer",
    [string]$Url,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$db = Join-Path $Repo "data\training.db"
$tokens = Join-Path $env:USERPROFILE ".garminconnect\garmin_tokens.json"

foreach ($tool in "ssh", "scp", "uv") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "'$tool' not found. ssh/scp: Settings > Apps > Optional features > OpenSSH Client."
    }
}
if (-not (Test-Path $db)) { Write-Error "No database at $db." }
if (-not (Test-Path $tokens)) { Write-Error "No Garmin tokens at $tokens - run 'uv run training login' first." }

Write-Host "== 1/4 Stop the local app and finish the database file"
& (Join-Path $PSScriptRoot "start_app.ps1") -Stop
Push-Location $Repo
try {
    uv run python -c "import sqlite3; c = sqlite3.connect(r'data\training.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
    if ($LASTEXITCODE -ne 0) { Write-Error "Could not checkpoint the database (is the app still open?)." }
} finally {
    Pop-Location
}

Write-Host "== 2/4 Copy the database and the Garmin login to $Server"
$exists = (ssh $Server "test -f '$RemoteDir/data/training.db' && echo yes || echo no" | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { Write-Error "ssh $Server failed - is the server on and the name right?" }
if ($exists -eq "yes" -and -not $Force) {
    Write-Error "The server already has $RemoteDir/data/training.db. Re-run with -Force to overwrite it (stop the server first: docker compose down)."
}
ssh $Server "mkdir -p '$RemoteDir/data' ~/.garminconnect && chmod 700 ~/.garminconnect"
if ($LASTEXITCODE -ne 0) { Write-Error "Could not create the folders on the server." }
scp $db "${Server}:$RemoteDir/data/training.db"
if ($LASTEXITCODE -ne 0) { Write-Error "Copying the database failed." }
scp $tokens "${Server}:.garminconnect/garmin_tokens.json"
if ($LASTEXITCODE -ne 0) { Write-Error "Copying the Garmin tokens failed." }
ssh $Server "chmod 600 ~/.garminconnect/garmin_tokens.json"

Write-Host "== 3/4 Remove the Windows morning task (the server takes over)"
& (Join-Path $PSScriptRoot "install_task_windows.ps1") -Remove

if ($Url) {
    Write-Host "== 4/4 Desktop icon -> $Url"
    & (Join-Path $PSScriptRoot "install_shortcut_windows.ps1") -Url $Url
} else {
    Write-Host "== 4/4 Skipped the desktop icon (no -Url). After server_setup.sh prints the address, run:"
    Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1 -Url https://<server>.<tailnet>.ts.net"
}
Write-Host ""
Write-Host "Done. On the server: cd $RemoteDir && scripts/server_setup.sh"
Write-Host "Your local copy in data\ stays as a backup; the PC no longer syncs."
