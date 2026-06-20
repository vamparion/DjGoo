$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $ProjectRoot "logs"
$logPath = Join-Path $logDir "startup.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Show-StatusMessage {
    param(
        [string]$Message,
        [string]$Title = "DjGoo"
    )

    try {
        $shell = New-Object -ComObject WScript.Shell
        $null = $shell.Popup($Message, 5, $Title, 64)
    } catch {
        Write-Host $Message
    }
}

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @("redbot.exe", "python.exe", "java.exe", "powershell.exe")) -and
    ($_.ProcessId -ne $PID) -and
    ($_.CommandLine -like "*Documents\DiscordBot*" -or $_.CommandLine -like "*data\discordbot\cogs\Audio\Lavalink.jar*")
}

if ($alreadyRunning) {
    "DjGoo is already running. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
    Show-StatusMessage "DjGoo is already running."
    exit 0
}

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $ProjectRoot "start-djgoo.ps1") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

"Started DjGoo. $(Get-Date -Format s)" | Add-Content -LiteralPath $logPath
Show-StatusMessage "DjGoo is starting. Give it about 10 seconds to connect to Discord."
