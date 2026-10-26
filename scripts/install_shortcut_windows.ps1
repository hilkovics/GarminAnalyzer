<#
.SYNOPSIS
  Put a "Training Analytics" icon on the desktop (and in the Start menu) that opens the app.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1            # app on this PC
  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1 -Url https://trening.tail1234.ts.net
  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1 -Remove    # remove

.NOTES
  - Without -Url the icon runs scripts\start_app.ps1 without a console window: it starts the local server when
    needed and opens the app (see that script).
  - With -Url (the home server, docs/SERVER.md) the icon just opens that address as an app window in Edge
    (else in the default browser); nothing runs on this PC.
  - Re-running replaces the icons.
#>
param(
    [string]$Url,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Name = "Training Analytics.lnk"
$Targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) $Name),
    (Join-Path ([Environment]::GetFolderPath("Programs")) $Name)
)

if ($Remove) {
    foreach ($path in $Targets) {
        if (Test-Path $path) {
            Remove-Item $path
            Write-Host "Removed $path"
        }
    }
    exit 0
}

if ($Url -and $Url -notmatch '^https?://') {
    Write-Error "-Url must start with https:// (or http://), got '$Url'."
}
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$script = Join-Path $PSScriptRoot "start_app.ps1"
$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$shell = New-Object -ComObject WScript.Shell
foreach ($path in $Targets) {
    $shortcut = $shell.CreateShortcut($path)
    if ($Url -and $edge) {
        $shortcut.TargetPath = $edge
        $shortcut.Arguments = "--app=$Url"
    } elseif ($Url) {
        $shortcut.TargetPath = Join-Path $env:SystemRoot "explorer.exe"
        $shortcut.Arguments = $Url
    } else {
        $shortcut.TargetPath = $powershell
        $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
    }
    $shortcut.WorkingDirectory = $Repo
    $shortcut.IconLocation = (Join-Path $PSScriptRoot "assets\app.ico") + ",0"
    $shortcut.Description = "Training Analytics - záťaž, forma, spánok a plán"
    $shortcut.WindowStyle = if ($Url) { 1 } else { 7 }  # 7 = minimized: no console flash for the local launcher
    $shortcut.Save()
    Write-Host "Created $path"
}
Write-Host "Double-click 'Training Analytics' on the desktop to open the app."
