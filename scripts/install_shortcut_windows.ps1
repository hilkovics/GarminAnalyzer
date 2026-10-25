<#
.SYNOPSIS
  Put a "Training Analytics" icon on the desktop (and in the Start menu) that opens the app.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1            # install
  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1 -Remove    # remove

.NOTES
  - The icon runs scripts\start_app.ps1 without a console window: it starts the local server when needed
    and opens the app (see that script). Re-running replaces the icons.
#>
param(
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

$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$script = Join-Path $PSScriptRoot "start_app.ps1"
$shell = New-Object -ComObject WScript.Shell
foreach ($path in $Targets) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
    $shortcut.WorkingDirectory = $Repo
    $shortcut.IconLocation = (Join-Path $PSScriptRoot "assets\app.ico") + ",0"
    $shortcut.Description = "Training Analytics - záťaž, forma, spánok a plán"
    $shortcut.WindowStyle = 7  # minimized: no console flash
    $shortcut.Save()
    Write-Host "Created $path"
}
Write-Host "Double-click 'Training Analytics' on the desktop to open the app."
