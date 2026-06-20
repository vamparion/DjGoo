$ErrorActionPreference = "Stop"

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @("redbot.exe", "python.exe", "java.exe", "powershell.exe")) -and
    ($_.CommandLine -like "*Documents\DiscordBot*" -or $_.CommandLine -like "*data\discordbot\cogs\Audio\Lavalink.jar*")
}

foreach ($proc in ($targets | Where-Object { $_.ProcessId -ne $PID } | Sort-Object ProcessId -Descending)) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped DjGoo project Redbot processes."
