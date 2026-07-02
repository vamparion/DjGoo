$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$targets = Get-CimInstance Win32_Process | Where-Object {
    (
        ($_.Name -eq "redbot.exe" -and $_.CommandLine -like "*discordbot*") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*tools\start_redbot_selector.py*") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*-m voice.djgoo_voice_listener*") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*voice.djgoo_voice_listener*") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*-m redbot*discordbot*") -or
        ($_.Name -eq "java.exe" -and $_.CommandLine -like "*Lavalink.jar*") -or
        ($_.Name -eq "powershell.exe" -and $_.CommandLine -like "*-File*$ProjectRoot\start-djgoo.ps1*")
    )
}

foreach ($proc in ($targets | Where-Object { $_.ProcessId -ne $PID } | Sort-Object ProcessId -Descending)) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped DjGoo project Redbot processes."
