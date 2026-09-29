@echo off
setlocal

set "PYTHON_EXE=D:\code\social-auto-upload\autoup\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8765"

powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%APP_URL%/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if %errorlevel% equ 0 (
    start "" "%APP_URL%"
    exit /b 0
)

if not exist "%PYTHON_EXE%" (
    echo Python environment was not found:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

cd /d "%~dp0"
echo Starting Doubao task manager...
echo URL: %APP_URL%
"%PYTHON_EXE%" "%~dp0start_web.py"

set "APP_EXIT_CODE=%errorlevel%"
echo.
echo Server stopped with exit code %APP_EXIT_CODE%.
pause
exit /b %APP_EXIT_CODE%
