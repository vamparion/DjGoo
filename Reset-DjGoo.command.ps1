$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "reset.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

"Resetting DjGoo. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath

& (Join-Path $ProjectRoot "stop-djgoo.ps1") *> $null
"Stopped existing DjGoo processes. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
Start-Sleep -Seconds 3
$env:DJGOO_RESUME_ACTIVE_RADIO = "1"
& (Join-Path $ProjectRoot "Start-DjGoo.command.ps1") *> $null
Remove-Item Env:\DJGOO_RESUME_ACTIVE_RADIO -ErrorAction SilentlyContinue
"Started DjGoo stack. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath

"Reset command finished. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
