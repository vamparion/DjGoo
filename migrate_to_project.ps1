$ErrorActionPreference = "Stop"

$ProjectRoot = "C:\Users\VERA\Documents\DiscordBot"
$OldRedRoot = Join-Path $env:LOCALAPPDATA "Red-DiscordBot\Red-DiscordBot"
$NewRedRoot = Join-Path $ProjectRoot ".localappdata\Red-DiscordBot\Red-DiscordBot"
$NewDataPath = Join-Path $ProjectRoot "data\discordbot"

New-Item -ItemType Directory -Force -Path $NewRedRoot, $NewDataPath | Out-Null
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

Copy-Item -LiteralPath (Join-Path $OldRedRoot "config.json") -Destination (Join-Path $NewRedRoot "config.json") -Force
Copy-Item -LiteralPath (Join-Path $OldRedRoot "data\discordbot") -Destination (Join-Path $ProjectRoot "data") -Recurse -Force

$configPath = Join-Path $NewRedRoot "config.json"
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
$config.discordbot.DATA_PATH = $NewDataPath
[System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 10), $Utf8NoBom)

$settingsPath = Join-Path $NewDataPath "core\settings.json"
$settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json
$settings.'0'.GLOBAL.prefix = @(
    "!",
    "DjGoo ", "DjGoo, ", "DjGoo: ",
    "djgoo ", "djgoo, ", "djgoo: ",
    "DJGoo ", "DJGoo, ", "DJGoo: ",
    "DJ Goo ", "DJ Goo, ", "DJ Goo: ",
    "dj goo ", "dj goo, ", "dj goo: "
)
[System.IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json -Depth 100 -Compress), $Utf8NoBom)

Write-Host "Migrated Red data into $ProjectRoot"
