@echo off
rem SSBU recomp: the launcher window (Launcher.ps1 next to this file; copied into build\ by scripts\setup.py link).
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Launcher.ps1"
