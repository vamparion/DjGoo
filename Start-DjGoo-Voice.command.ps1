$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "voice-startup.log"
$python = Join-Path $ProjectRoot ".voice-venv\Scripts\python.exe"
$listenerLogPath = Join-Path $logDir "voice-listener.log"
$listenerErrorLogPath = Join-Path $logDir "voice-listener.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Show-StatusMessage {
    param(
        [string]$Message,
        [string]$Title = "DjGoo Voice"
    )

    try {
        $shell = New-Object -ComObject WScript.Shell
        $null = $shell.Popup($Message, 5, $Title, 64)
    } catch {
        Write-Host $Message
    }
}

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @("python.exe")) -and
    ($_.ProcessId -ne $PID) -and
    ($_.CommandLine -like "*voice.djgoo_voice_listener*")
}

if ($alreadyRunning) {
    "DjGoo voice listener is already running. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
    Show-StatusMessage "DjGoo voice listener is already running."
    exit 0
}

if (!(Test-Path $python)) {
    Show-StatusMessage "Voice dependencies are not installed. Run install-voice-deps.ps1 first."
    throw "Voice dependencies are not installed. Run .\install-voice-deps.ps1 first."
}

$env:PYTHONPATH = $ProjectRoot
Start-Process `
    -FilePath $python `
    -ArgumentList "-m", "voice.djgoo_voice_listener", "--project-root", $ProjectRoot `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $listenerLogPath `
    -RedirectStandardError $listenerErrorLogPath `
    -WindowStyle Hidden

"Started DjGoo voice listener. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
Show-StatusMessage "DjGoo voice listener is starting. The first run may download the Whisper model."
