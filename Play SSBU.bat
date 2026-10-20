@echo off
rem Starts the game built by Install SSBU.bat. The install location (default build\, or the folder chosen in the installer
rem window, remembered in build_location.txt) is read by scripts\run.py; your saves go to its saves\ folder.
cd /d "%~dp0"
set "PY="
rem the private Python of THIS folder first: build\python_path.txt keeps an absolute path, which is wrong after the folder moved
if exist deps\python\python.exe set "PY=%~dp0deps\python\python.exe"
if not defined PY if exist build\python_path.txt set /p PY=<build\python_path.txt
if defined PY if not exist "%PY%" set "PY="
if not defined PY set "PY=python"
"%PY%" scripts\run.py --play --seconds 0
if errorlevel 1 pause
