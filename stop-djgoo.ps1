$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$Launcher = Join-Path $ProjectRoot "tools\djgoo_stack.py"

if (!(Test-Path $Python)) {
    throw "DjGoo Python was not found at $Python"
}

Start-Process -FilePath $Python -ArgumentList @("`"$Launcher`"", "stop") -WorkingDirectory $ProjectRoot -WindowStyle Hidden
exit 0
