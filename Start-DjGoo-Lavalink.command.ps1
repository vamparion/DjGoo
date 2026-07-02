$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$audioDir = Join-Path $ProjectRoot "data\discordbot\cogs\Audio"
$java = "C:\Program Files\Eclipse Adoptium\jdk-17.0.17.10-hotspot\bin\java.exe"
$jar = Join-Path $audioDir "Lavalink.jar"
$logDir = Join-Path $ProjectRoot "logs"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$alreadyRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "java.exe") -and
    ($_.CommandLine -like "*Lavalink.jar*")
}

if ($alreadyRunning) {
    exit 0
}

if (!(Test-Path $java)) {
    throw "Java was not found at $java"
}

if (!(Test-Path $jar)) {
    throw "Lavalink.jar was not found at $jar"
}

Start-Process `
    -FilePath $java `
    -ArgumentList "-Xms64M", "-Xmx512M", "-jar", "Lavalink.jar" `
    -WorkingDirectory $audioDir `
    -RedirectStandardOutput (Join-Path $logDir "lavalink-external.log") `
    -RedirectStandardError (Join-Path $logDir "lavalink-external.err.log") `
    -WindowStyle Hidden
