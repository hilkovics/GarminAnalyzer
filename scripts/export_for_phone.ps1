<#
.SYNOPSIS
  Prepare the move of the app from this Windows PC to an Android phone (docs/ANDROID.md, step 3).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\export_for_phone.ps1
  powershell -ExecutionPolicy Bypass -File scripts\export_for_phone.ps1 -KeepTask

.NOTES
  What it does, in this order:
  1. stops the local app server (if it runs) and writes a consistent copy of data\training.db with SQLite's
     backup API (correct even while something else still has the database open);
  2. copies the Garmin login (%USERPROFILE%\.garminconnect\garmin_tokens.json) and the settings (.env with the
     Telegram / Anthropic keys, as env.txt) next to it, into %USERPROFILE%\GarminAnalyzer-telefon - not on the
     Desktop, which OneDrive often backs up to the cloud;
  3. removes the Windows morning task, so only the phone syncs and pushes to Garmin from now on
     (-KeepTask keeps it, e.g. for a trial; two machines with two databases would push every workout twice).
  Then copy the folder's files to the phone's Download\GarminAnalyzer folder with a USB cable or Quick Share
  (not through a cloud drive: they hold your Garmin login and keys) and run scripts/android/setup.sh there.
#>
param(
    [string]$Out = (Join-Path $env:USERPROFILE "GarminAnalyzer-telefon"),
    [switch]$KeepTask
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$db = Join-Path $Repo "data\training.db"
$settings = Join-Path $Repo ".env"
$tokens = Join-Path $env:USERPROFILE ".garminconnect\garmin_tokens.json"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Error "uv not found on PATH." }
if (-not (Test-Path $db)) { Write-Error "No database at $db." }
if (-not (Test-Path $tokens)) { Write-Error "No Garmin tokens at $tokens - run 'uv run training login' first." }
if ($Out -match "OneDrive") { Write-Error "$Out is synced by OneDrive - choose another -Out (the files hold your Garmin login)." }

Write-Host "== 1/3 Stop the local app and copy the database"
& (Join-Path $PSScriptRoot "start_app.ps1") -Stop
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$target = Join-Path $Out "training.db"
if (Test-Path $target) { Remove-Item $target -Force }
Push-Location $Repo
try {
    $env:GA_EXPORT_TARGET = $target
    uv run python -c "import os, sqlite3; s = sqlite3.connect(r'data\training.db'); d = sqlite3.connect(os.environ['GA_EXPORT_TARGET']); s.backup(d); d.close(); s.close()"
    if ($LASTEXITCODE -ne 0) { Write-Error "Could not copy the database." }
} finally {
    Remove-Item Env:GA_EXPORT_TARGET -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "== 2/3 Copy the Garmin login and the settings to $Out"
Copy-Item $tokens (Join-Path $Out "garmin_tokens.json") -Force
if (Test-Path $settings) {
    Copy-Item $settings (Join-Path $Out "env.txt") -Force
    $note = "and env.txt (Telegram / AI keys)"
} else {
    $note = "(no .env on this PC - Telegram stays off on the phone until you add the keys there, docs/ANDROID.md)"
}
$size = [math]::Round((Get-Item $target).Length / 1MB, 1)
Write-Host "   training.db ($size MB), garmin_tokens.json $note"

if ($KeepTask) {
    Write-Host "== 3/3 Kept the Windows morning task (-KeepTask). Remove it once the phone runs:"
    Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove"
} else {
    Write-Host "== 3/3 Remove the Windows morning task (the phone takes over)"
    & (Join-Path $PSScriptRoot "install_task_windows.ps1") -Remove
}
Write-Host ""
Write-Host "Next: copy the files in $Out to the phone's Download\GarminAnalyzer folder (USB cable or Quick Share),"
Write-Host "then in Termux: bash ~/GarminAnalyzer/scripts/android/setup.sh   (docs/ANDROID.md)"
Write-Host "Delete $Out afterwards - it holds your Garmin login."
