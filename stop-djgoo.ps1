$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @("redbot.exe", "python.exe", "java.exe", "powershell.exe")) -and
    (
        $_.CommandLine -like "*$ProjectRoot*" -or
        $_.CommandLine -like "*redbot.exe*discordbot*" -or
        $_.CommandLine -like "*tools\start_redbot_selector.py*" -or
        $_.CommandLine -like "*-m redbot*discordbot*" -or
        $_.CommandLine -like "*start-djgoo.ps1*" -or
        $_.CommandLine -like "*voice.djgoo_voice_listener*" -or
        $_.CommandLine -like "*Lavalink.jar*" -or
        $_.CommandLine -like "*data\discordbot\cogs\Audio\Lavalink.jar*"
    )
}

foreach ($proc in ($targets | Where-Object { $_.ProcessId -ne $PID } | Sort-Object ProcessId -Descending)) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped DjGoo project Redbot processes."
