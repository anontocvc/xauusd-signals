@echo off
title XAUUSD Ngrok Tunnel
color 0B
cls

echo.
echo  ==========================================
echo   XAUUSD NGROK TUNNEL - MOBILE ACCESS
echo  ==========================================
echo.
echo  This gives your phone access from ANY network.
echo  (mobile data, different WiFi, anywhere in world)
echo.

REM Check if ngrok is installed
where ngrok >nul 2>&1
if errorlevel 1 (
    echo  Ngrok not found. Installing...
    echo.
    echo  Option 1: Download from https://ngrok.com/download
    echo  Option 2: Run:  winget install ngrok
    echo  Option 3: Run:  choco install ngrok
    echo.
    echo  After install, run this file again.
    echo.
    pause
    start https://ngrok.com/download
    exit
)

echo  Ngrok found. Starting tunnel on port 5000...
echo.
echo  IMPORTANT: Make sure  python app.py  is running first!
echo.
echo  After ngrok starts, copy the  https://xxxx.ngrok-free.app
echo  URL and open it on your phone like this:
echo.
echo    https://xxxx.ngrok-free.app/mobile
echo.
echo  ==========================================
echo.
ngrok http 5000

pause
