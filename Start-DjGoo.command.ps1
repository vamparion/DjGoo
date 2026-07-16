$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "startup.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:DJGOO_EVENT_LOG = Join-Path $logDir "djgoo-events.jsonl"

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @("redbot.exe", "python.exe", "powershell.exe")) -and
    ($_.ProcessId -ne $PID) -and
    (
        $_.CommandLine -like "*redbot.exe*discordbot*" -or
        $_.CommandLine -like "*tools\start_redbot_selector.py*" -or
        $_.CommandLine -like "*-m redbot*discordbot*" -or
        $_.CommandLine -like "*start-djgoo.ps1*"
    )
}

if ($alreadyRunning) {
    & (Join-Path $ProjectRoot ".venv\Scripts\python.exe") (Join-Path $ProjectRoot "tools\djgoo_health.py") --project-root $ProjectRoot 2>&1 |
        ForEach-Object { $_ | Add-Content -LiteralPath $logPath }
    if ($LASTEXITCODE -eq 0) {
        "DjGoo is already running and healthy. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
        exit 0
    }
    "DjGoo was running but unhealthy; restarting. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
    & (Join-Path $ProjectRoot "stop-djgoo.ps1") *> $null
    Start-Sleep -Seconds 3
}

& (Join-Path $ProjectRoot "Repair-DjGoo-IPv6-Audio.ps1") *> $null
& (Join-Path $ProjectRoot "Start-DjGoo-Lavalink.command.ps1") *> $null
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") (Join-Path $ProjectRoot "tools\wait_for_discord_network.py") --timeout 120 --stable-checks 5 2>&1 |
    ForEach-Object { $_ | Add-Content -LiteralPath $logPath }
if ($LASTEXITCODE -ne 0) {
    throw "Discord network was not ready. See $logPath."
}
Start-Sleep -Seconds 7

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $ProjectRoot "start-djgoo.ps1") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

"Started DjGoo. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
