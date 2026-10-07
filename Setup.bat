@echo off
rem One-time setup on a new computer: creates .venv in this folder. Nothing is installed globally.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause
