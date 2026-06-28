$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "control-panel.log"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (!(Test-Path $python)) {
    throw "Bot dependencies are not installed. Missing $python"
}

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe") -and
    ($_.ProcessId -ne $PID) -and
    ($_.CommandLine -like "*control_panel.server*")
}

if ($alreadyRunning) {
    "DjGoo control panel is already running. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
    Start-Process "http://127.0.0.1:8765"
    exit 0
}

Start-Process `
    -FilePath $python `
    -ArgumentList "-m", "control_panel.server", "--project-root", $ProjectRoot, "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError (Join-Path $logDir "control-panel.err.log") `
    -WindowStyle Hidden

Start-Sleep -Seconds 1
Start-Process "http://127.0.0.1:8765"
"Started DjGoo control panel. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
