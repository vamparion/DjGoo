$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Launcher = Join-Path $ProjectRoot "tools\djgoo_stack.py"

& $Python $Launcher reset
exit $LASTEXITCODE
