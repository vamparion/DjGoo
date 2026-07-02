$ErrorActionPreference = "Stop"

Write-Host "DjGoo repair: resetting Windows Winsock catalog." -ForegroundColor Cyan
Write-Host "This fixes Python/Redbot startup hangs when local sockets stop working." -ForegroundColor Cyan
Write-Host ""

netsh winsock reset

Write-Host ""
Write-Host "Winsock reset requested. Restart Windows before starting DjGoo again." -ForegroundColor Yellow
Read-Host "Press Enter to close"
