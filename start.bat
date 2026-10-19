@echo off
REM PanJuan PaperForge - one-click start (double-click me).
REM Starts the local server in the background if it is not running, waits until
REM /api/health really answers, then opens your browser.
REM If the server is already up, it just opens the page (no second process).
REM NOTE: keep this file ASCII-only + CRLF. cmd reads .bat with the system ANSI
REM codepage (GBK on zh-CN), so UTF-8 Chinese here would break command parsing.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start.ps1" %*
if errorlevel 1 (
  echo.
  echo Something went wrong. The window stays open so you can read the message.
  pause
)
