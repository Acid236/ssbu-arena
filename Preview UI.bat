@echo off
cd /d "%~dp0"
set "PY=python"
if exist deps\python\python.exe set "PY=%~dp0deps\python\python.exe"
"%PY%" tools\ui\build_runtime.py
if errorlevel 1 goto failed
"%PY%" tools\ui\prepare_menu.py --labels tools\ui\menu_labels_en.json
if errorlevel 1 goto failed
"%PY%" tools\ui\menu_probe.py --tag preview --visible --play
if errorlevel 1 goto failed
exit /b 0
:failed
pause
exit /b 1
