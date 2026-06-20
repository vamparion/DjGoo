$ErrorActionPreference = "Stop"

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe") -and
    ($_.CommandLine -like "*voice.djgoo_voice_listener*")
}

foreach ($proc in $targets) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped DjGoo voice listener."
