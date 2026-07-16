$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$voiceVenv = Join-Path $ProjectRoot ".voice-venv"
$python = Join-Path $voiceVenv "Scripts\python.exe"

if (!(Test-Path $python)) {
    & "C:\Python311\python.exe" -m venv $voiceVenv
}

& $python -m pip install --upgrade pip
& $python -m pip install numpy sounddevice requests faster-whisper keyboard
