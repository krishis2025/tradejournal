@echo off
cd /d "%~dp0"

echo.
echo   +====================================+
echo   ^|    TRADE JOURNAL  v1.0             ^|
echo   +====================================+
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found.
    echo   Install from: https://python.org/downloads
    echo   Make sure to check "Add Python to PATH" during install!
    pause
    exit /b 1
)

echo   Python found: 
python --version

:: Create venv if needed
if not exist ".venv" (
    echo   Creating virtual environment (first run only)...
    python -m venv .venv
)

:: Activate
call .venv\Scripts\activate.bat

:: Install dependencies
echo   Installing/checking dependencies...
pip install -q -r requirements.txt

echo.
echo   Server starting...
echo   Open your browser and go to:
echo.
echo       http://127.0.0.1:5000
echo.
echo   Press Ctrl+C to stop.
echo.

:: Open browser
timeout /t 2 /nobreak >nul
start http://127.0.0.1:5000

python server.py
if errorlevel 1 (
    echo.
    echo   ERROR: Server failed to start. See message above.
    pause
)
