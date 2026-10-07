@echo off
rem Builds dist\Auraplex_Material_Stock_Checker and the Portable ZIP using the project .venv only.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_portable.ps1" %*
if errorlevel 1 pause
