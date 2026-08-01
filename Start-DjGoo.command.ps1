$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Launcher = Join-Path $ProjectRoot "tools\djgoo_stack.py"
$LogDir = Join-Path $ProjectRoot "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

& $Python $Launcher start
exit $LASTEXITCODE
