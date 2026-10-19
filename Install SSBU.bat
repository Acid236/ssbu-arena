@echo off
rem One click: a private Python in deps\python (scripts\bootstrap.ps1), then the installer window (scripts\installer_window.ps1).
rem BUILDING.md has the same steps by hand.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
if errorlevel 1 pause
