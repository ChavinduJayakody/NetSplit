@echo off
title Network Monitor (Windows)
echo ==============================================
echo   Network Monitor - Wi-Fi & Throne VPN Split
echo ==============================================
echo.

:: Check for python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

:: Create venv if not present
if not exist "venv" (
    echo [*] Creating Python virtual environment...
    python -m venv venv
)

:: Activate venv and install dependencies
call venv\Scripts\activate.bat
echo [*] Checking dependencies...
pip install -r requirements.txt --quiet

echo [*] Launching Desktop App...
python main.py --desktop %*

pause
