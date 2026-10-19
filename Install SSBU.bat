@echo off
rem One click: opens the installer window (scripts\installer_gui.py). BUILDING.md has the same steps by hand.
cd /d "%~dp0"
where pythonw >nul 2>nul || (echo Python 3.10 or newer is needed: https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again. & pause & exit /b 1)
start "" pythonw scripts\installer_gui.py
