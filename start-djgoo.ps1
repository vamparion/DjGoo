$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:REDBOT_CONFIG_DIR = Join-Path $ProjectRoot ".localappdata\Red-DiscordBot\Red-DiscordBot"
$env:DJGOO_SECRETS_FILE = Join-Path $ProjectRoot "config\secrets.json"

Set-Location $ProjectRoot
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") (Join-Path $ProjectRoot "tools\start_redbot_selector.py")
