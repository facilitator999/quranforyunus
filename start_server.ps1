Set-Location $PSScriptRoot

Write-Host "Freeing port 3000..."
$listener = netstat -ano | Select-String ':3000\s.*LISTENING' | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -First 1
if ($listener) {
    Stop-Process -Id ([int]$listener) -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

Write-Host "Starting PHP server with MP3 Range/seek support..."
Write-Host "  http://localhost:3000"
Write-Host ""

php -S localhost:3000 router.php
