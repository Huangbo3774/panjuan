@echo off
REM PanJuan PanJuan Paper Printer - stop the local server (double-click me).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start.ps1" -Stop %*
timeout /t 2 >nul
