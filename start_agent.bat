@echo off
cd /d "%~dp0python"
echo ============================================
echo   AI Trading Agent - Starting...
echo ============================================
call .\venv\Scripts\python.exe main.py
pause
