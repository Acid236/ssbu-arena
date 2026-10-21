@echo off
rem SSBU recomp: the launcher window, SSBU Arena.exe (tools/launcher/arena) or else Launcher.ps1, next to this file
rem (copied into build\ by scripts\setup.py link).
if exist "%~dp0SSBU Arena.exe" (
  start "" "%~dp0SSBU Arena.exe"
) else (
  start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Launcher.ps1"
)
