$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "startup.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

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
    "DjGoo is already running. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
    exit 0
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

& (Join-Path $ProjectRoot "Start-DjGoo-Voice.command.ps1") *> $null

"Started DjGoo. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
