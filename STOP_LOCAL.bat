@echo off
setlocal
cd /d "%~dp0"

echo Stopping Marketing Telegram Bot local processes...
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_local.ps1"
pause
