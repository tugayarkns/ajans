@echo off
cd /d "%~dp0"
start "AJANS" cmd /k python service.py
timeout /t 3 >nul
start http://127.0.0.1:8765
