@echo off
setlocal
chcp 65001 >nul
title Qboard Installer Setup

cd /d "%~dp0"

echo =================================================================
echo   Qboard Whiteboard Enhancement Studio - Windows Installer
echo   מתקין אוטומטי למערכת שיפור לוח חכם לזום
echo =================================================================
echo.

:: 1. Check Python installation
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=python
    goto :RunInstaller
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set PY_CMD=py -3
    goto :RunInstaller
)

:: Python not found
echo [שגיאה] לא נמצאה התקנת Python במחשב!
echo [ERROR] Python was not detected in system PATH.
echo.
echo כדי להשתמש ב-Qboard, יש להתקין Python 3.9 ומעלה:
echo 1. היכנס לאתר הרשמי: https://www.python.org/downloads/
echo 2. בהתקנה סמן ב-V: "Add Python to PATH" (חשוב מאוד!)
echo 3. בסיום ההתקנה, הפעל מחדש את קובץ זה: install.bat
echo.
pause
exit /b 1

:RunInstaller
%PY_CMD% installer.py %*
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation process ended with code %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo Installation complete. Press any key to close this window...
pause >nul
endlocal
