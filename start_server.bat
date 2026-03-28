@echo off
cd /d "%~dp0"

echo Freeing port 3000 (closing any process using it^)...
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":3000 " ^| findstr LISTENING') do (
    taskkill /F /PID %%P >nul 2>&1
)
REM Brief pause so Windows releases the port
timeout /t 1 /nobreak >nul

echo Starting PHP built-in server...
echo   http://localhost:3000
echo   Optional: py serve_fast.py 3000 — Python static server with MP3 Range ^(seek^) support
echo.

php -S localhost:3000
if errorlevel 1 (
    echo.
    echo If "php" was not found, install PHP and add php.exe to PATH:
    echo   https://windows.php.net/download/
    echo.
    pause
)
