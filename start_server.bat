@echo off
cd /d "%~dp0"

echo Freeing port 3000 (closing any process using it^)...
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":3000 " ^| findstr LISTENING') do (
    taskkill /F /PID %%P >nul 2>&1
)
REM Brief pause so Windows releases the port
timeout /t 1 /nobreak >nul

echo Starting server...
echo.
py serve_fast.py 3000
if errorlevel 1 (
    echo.
    echo If "Python was not found", install Python from https://www.python.org/downloads/
    echo Or try: python serve_fast.py 3000
    pause
)
