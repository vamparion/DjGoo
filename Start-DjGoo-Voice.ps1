$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $ProjectRoot ".voice-venv\Scripts\python.exe"
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "voice-listener.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (!(Test-Path $python)) {
    throw "Voice dependencies are not installed. Run .\install-voice-deps.ps1 first."
}

Set-Location $ProjectRoot
$env:PYTHONPATH = $ProjectRoot
& $python -m voice.djgoo_voice_listener --project-root $ProjectRoot *>> $logPath
