<#
.SYNOPSIS
  Install (or remove) the daily `training morning` run in Windows Task Scheduler (PLAN phase 8).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1            # daily at 09:00
  powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -At 08:30
  powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove

.NOTES
  - Wakes the PC from sleep or hibernation at the run time (WakeToRun, wake timers switched on); Windows goes
    back to sleep on its own afterwards. A fully shut down PC cannot be woken by Windows - use Sleep instead of
    Shut down, or a BIOS "RTC wake" alarm (docs/OPERATIONS.md).
  - Runs even when nobody is signed in (logon type S4U, as your own user, no password stored) and without a
    console window. That needs administrator rights once: the script asks for them (UAC prompt). With
    -InteractiveOnly it installs the old way instead: only while you are signed in, no admin rights needed.
  - "Run as soon as possible after a missed start" is on: a PC that was off at the run time runs it on start.
  - Idempotent: re-running replaces the task. Output: data\logs\task.out; structured log: data\logs\training.log.
  - Run `uv run training login` once before.
#>
param(
    [string]$At = "09:00",
    [switch]$Remove,
    [switch]$InteractiveOnly,
    [string]$User = "$env:USERDOMAIN\$env:USERNAME"
)
$ErrorActionPreference = "Stop"
$TaskName = "GarminAnalyzer - training morning"
$Repo = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        try {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        } catch {
            Write-Error "Could not remove '$TaskName' (a task that runs without sign-in needs an administrator PowerShell to remove): $_"
        }
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

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $InteractiveOnly -and -not $isAdmin) {
    # ask once for admin rights and install for the signed-in user (not for the admin account, if it differs)
    Write-Host "Administrator rights are needed once so the run also works when nobody is signed in..."
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -At $At -User `"$User`""
    try {
        $elevated = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs -Wait -PassThru
    } catch {
        Write-Error "Administrator rights were refused. Run again, or use -InteractiveOnly (runs only while you are signed in)."
    }
    exit $elevated.ExitCode
}

New-Item -ItemType Directory -Force -Path (Join-Path $Repo "data\logs") | Out-Null
$command = "/c cd /d `"$Repo`" && `"$uv`" run training morning >> data\logs\task.out 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $command -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($At, "H:mm", [System.Globalization.CultureInfo]::InvariantCulture))
# RunOnlyIfNetworkAvailable: a run caught up right after wake waits for Wi-Fi instead of failing the sync
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
$description = "Garmin sync, metrics, plan, push to Garmin, Telegram (uv run training morning)"

if ($InteractiveOnly) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description $description -Force | Out-Null
    $mode = "only while $User is signed in"
} else {
    # S4U: runs as $User whether signed in or not, without a stored password and without a window
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description $description -Force | Out-Null
    $mode = "as $User, also when nobody is signed in"
    # "Allow wake timers" on mains and battery, else WakeToRun is ignored
    powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
    powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
    powercfg /SETACTIVE SCHEME_CURRENT
}

Write-Host "Installed: '$TaskName' daily at $At (local time), $mode; wakes the PC from sleep."
Write-Host "Test it now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Last result:  Get-ScheduledTaskInfo -TaskName '$TaskName'   (LastTaskResult 0 = OK)"
if (-not $InteractiveOnly) {
    Write-Host ""
    Write-Host "This window closes in 15 s."
    Start-Sleep -Seconds 15  # the elevated window would vanish before the messages can be read
}
