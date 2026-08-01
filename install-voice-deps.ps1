$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$voiceVenv = Join-Path $ProjectRoot ".voice-venv"
$python = Join-Path $voiceVenv "Scripts\python.exe"
$requirements = Join-Path $ProjectRoot "requirements-voice.txt"

if (!(Test-Path $python)) {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.11 -m venv $voiceVenv
    }
    else {
        $pythonCommand = Get-Command python.exe -ErrorAction Stop
        & $pythonCommand.Source -m venv $voiceVenv
    }
}

& $python -m pip install --upgrade pip
& $python -m pip install --requirement $requirements
