<#
.SYNOPSIS
  Open Training Analytics: start the local server if it is not running yet, then open the app window.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_app.ps1           # start (if needed) and open
  powershell -ExecutionPolicy Bypass -File scripts\start_app.ps1 -Stop     # stop the server

.NOTES
  - The desktop icon (scripts\install_shortcut_windows.ps1) runs this script without a console window.
  - The server is `uv run training api` on 127.0.0.1 (this computer only; the API has no login). It serves
    the React app and the API on one port. Its window is minimized; closing that window stops the server.
  - The app opens as its own window in Microsoft Edge (--app), else in the default browser.
  - Server output: data\logs\app.out.
#>
param(
    [int]$Port = 8000,
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Url = "http://127.0.0.1:$Port/"

function Show-Error([string]$Message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Message, "Training Analytics", "OK", "Error") | Out-Null
}

function Test-Server {
    try {
        $response = Invoke-WebRequest -Uri "$($Url)api/health" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-ServerProcessIds {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    return @($owners | Where-Object { $_ -and $_ -ne 0 })
}

if ($Stop) {
    $ids = Get-ServerProcessIds
    if (-not $ids) {
        Write-Host "No server is listening on port $Port."
        exit 0
    }
    foreach ($id in $ids) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped the server on port $Port."
    exit 0
}

if (-not (Test-Server)) {
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if (-not $uv) {
        Show-Error "Program 'uv' sa nenašiel. Nainštaluj ho (https://docs.astral.sh/uv/) a skús to znova."
        exit 1
    }
    if (-not (Test-Path (Join-Path $Repo "frontend\dist\index.html"))) {
        Show-Error "Chýba frontend\dist. Spusti 'git pull' v priečinku $Repo."
        exit 1
    }
    $logs = Join-Path $Repo "data\logs"
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $command = "/c title Training Analytics server && cd /d `"$Repo`" && `"$uv`" run training api --port $Port >> data\logs\app.out 2>&1"
    Start-Process -FilePath "cmd.exe" -ArgumentList $command -WorkingDirectory $Repo -WindowStyle Minimized | Out-Null

    $deadline = (Get-Date).AddSeconds(90)  # the first start may sync dependencies and migrate the database
    while (-not (Test-Server)) {
        if ((Get-Date) -gt $deadline) {
            Show-Error "Server sa nespustil do 90 s. Pozri $logs\app.out."
            exit 1
        }
        Start-Sleep -Milliseconds 500
    }
}

$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($edge) {
    Start-Process -FilePath $edge -ArgumentList "--app=$Url" | Out-Null
} else {
    Start-Process $Url | Out-Null
}
