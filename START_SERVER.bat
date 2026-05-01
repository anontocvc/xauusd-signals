@echo off
title XAUUSD Signal Server
color 0A
cls

echo.
echo  ==========================================
echo   XAUUSD PRO SIGNAL SYSTEM - STARTING
echo  ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.11 first.
    pause & exit
)

REM Install/check packages silently
echo  Checking packages...
pip install flask requests pandas numpy MetaTrader5 -q --exists-action i 2>nul
echo  Packages OK

echo.
echo  Starting server...
echo  ==========================================
echo.

REM Start server
python app.py

pause
