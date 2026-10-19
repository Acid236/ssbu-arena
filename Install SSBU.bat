@echo off
rem One click: finds or installs Python (scripts\bootstrap.ps1), then opens the installer window (scripts\installer_gui.py).
rem BUILDING.md has the same steps by hand.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
if errorlevel 1 pause
