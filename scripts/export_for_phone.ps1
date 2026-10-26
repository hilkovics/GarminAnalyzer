<#
.SYNOPSIS
  Prepare the move of the app from this Windows PC to an Android phone (docs/ANDROID.md, step 3).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\export_for_phone.ps1
  powershell -ExecutionPolicy Bypass -File scripts\export_for_phone.ps1 -KeepTask

.NOTES
  What it does, in this order:
  1. stops the local app server (if it runs) and folds the SQLite WAL into data\training.db;
  2. copies data\training.db and the Garmin login (%USERPROFILE%\.garminconnect\garmin_tokens.json) into the
     folder GarminAnalyzer-telefon on your Desktop;
  3. removes the Windows morning task, so only the phone syncs and pushes to Garmin from now on
     (-KeepTask keeps it, e.g. for a trial; two machines with two databases would push every workout twice).
  Then copy the folder's two files to the phone's Download\GarminAnalyzer folder with a USB cable or Quick Share
  (not through a cloud drive: the token file is your Garmin login) and run scripts/android/setup.sh there.
#>
param(
    [string]$Out = (Join-Path ([Environment]::GetFolderPath("Desktop")) "GarminAnalyzer-telefon"),
    [switch]$KeepTask
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$db = Join-Path $Repo "data\training.db"
$tokens = Join-Path $env:USERPROFILE ".garminconnect\garmin_tokens.json"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Error "uv not found on PATH." }
if (-not (Test-Path $db)) { Write-Error "No database at $db." }
if (-not (Test-Path $tokens)) { Write-Error "No Garmin tokens at $tokens - run 'uv run training login' first." }

Write-Host "== 1/3 Stop the local app and finish the database file"
& (Join-Path $PSScriptRoot "start_app.ps1") -Stop
Push-Location $Repo
try {
    uv run python -c "import sqlite3; c = sqlite3.connect(r'data\training.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
    if ($LASTEXITCODE -ne 0) { Write-Error "Could not checkpoint the database (is the app still open?)." }
} finally {
    Pop-Location
}

Write-Host "== 2/3 Copy the database and the Garmin login to $Out"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Copy-Item $db (Join-Path $Out "training.db") -Force
Copy-Item $tokens (Join-Path $Out "garmin_tokens.json") -Force
$size = [math]::Round((Get-Item (Join-Path $Out "training.db")).Length / 1MB, 1)
Write-Host "   training.db ($size MB) and garmin_tokens.json"

if ($KeepTask) {
    Write-Host "== 3/3 Kept the Windows morning task (-KeepTask). Remove it once the phone runs:"
    Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove"
} else {
    Write-Host "== 3/3 Remove the Windows morning task (the phone takes over)"
    & (Join-Path $PSScriptRoot "install_task_windows.ps1") -Remove
}
Write-Host ""
Write-Host "Next: copy both files to the phone's Download\GarminAnalyzer folder (USB cable or Quick Share),"
Write-Host "then in Termux: bash ~/GarminAnalyzer/scripts/android/setup.sh   (docs/ANDROID.md)"
Write-Host "Delete the folder $Out afterwards - garmin_tokens.json is your Garmin login."
