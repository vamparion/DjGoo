$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$script = Join-Path $ProjectRoot "tools\configure_audio_ipv6.py"

& $python $script

Write-Host "DjGoo Audio is configured to use external IPv6 Lavalink at [::1]:2333."
