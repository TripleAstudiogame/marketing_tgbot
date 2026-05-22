@echo off
setlocal
cd /d "%~dp0"

echo Starting Marketing Telegram Bot in production mode...
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_production.ps1"

if errorlevel 1 (
  echo.
  echo Production startup failed. Check logs.
  pause
)

