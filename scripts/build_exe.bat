@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo   Building NetSplit Standalone Windows Executable (.exe)
echo =======================================================

cd /d "%~dp0\.."

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Install build dependencies
echo [*] Installing PyInstaller and dependencies...
pip install --quiet pyinstaller -r requirements.txt

:: Generate executable
echo [*] Running PyInstaller...
pyinstaller --clean --noconfirm packaging\NetSplit.spec

if %errorlevel% equ 0 (
    copy /y "dist\NetSplit.exe" "dist\NetSplit-1.7.1.exe" >nul 2>&1
    echo =======================================================
    echo   [SUCCESS] Standalone Executable built at:
    echo   dist\NetSplit-1.7.1.exe
    echo =======================================================
) else (
    echo [!] Build failed with exit code %errorlevel%
)

pause
