<#
.SYNOPSIS
  Install (or remove) the daily `training morning` run in Windows Task Scheduler (PLAN phase 8).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1            # daily at 06:00
  powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -At 05:45
  powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove

.NOTES
  - Runs as the current user (the Garmin tokens live in %USERPROFILE%\.garminconnect), only while logged on.
  - "Run as soon as possible after a missed start" is on: a laptop that slept through 06:00 runs it on wake.
  - Idempotent: re-running replaces the task. Output: data\logs\task.out; structured log: data\logs\training.log.
  - Run `uv run training login` once before.
#>
param(
    [string]$At = "06:00",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$TaskName = "GarminAnalyzer - training morning"
$Repo = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the task '$TaskName'."
    } else {
        Write-Host "No task '$TaskName' found."
    }
    exit 0
}

if ($At -notmatch '^([01]?\d|2[0-3]):[0-5]\d$') {
    Write-Error "Time must be HH:MM, got '$At'."
}
$uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $uv) {
    Write-Error "uv not found on PATH - install it first (https://docs.astral.sh/uv/)."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Repo "data\logs") | Out-Null
$command = "/c cd /d `"$Repo`" && `"$uv`" run training morning >> data\logs\task.out 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $command -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($At, "H:mm", [System.Globalization.CultureInfo]::InvariantCulture))
# RunOnlyIfNetworkAvailable: a run caught up right after wake waits for Wi-Fi instead of failing the sync
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Garmin sync, metrics, plan, push to Garmin, Telegram (uv run training morning)" -Force | Out-Null

Write-Host "Installed: '$TaskName' daily at $At (local time)."
Write-Host "Test it now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Last result:  Get-ScheduledTaskInfo -TaskName '$TaskName'"
