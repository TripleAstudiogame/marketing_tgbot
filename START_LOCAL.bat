@echo off
setlocal
cd /d "%~dp0"

echo Starting Marketing Telegram Bot...
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local_with_admin.ps1"

if errorlevel 1 (
  echo.
  echo Startup failed. Check the message above.
  pause
)

