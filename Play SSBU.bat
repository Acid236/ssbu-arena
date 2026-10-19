@echo off
rem Starts the game built by Install SSBU.bat. Your saves go to build\saves.
cd /d "%~dp0"
if not exist build\work\ssbu_native.exe (echo The game is not built yet: double-click "Install SSBU.bat" first. & pause & exit /b 1)
set "PY="
if exist build\python_path.txt set /p PY=<build\python_path.txt
if not defined PY set "PY=python"
if not exist build\saves mkdir build\saves
"%PY%" scripts\run.py --userdata build\saves --seconds 0
if errorlevel 1 pause
