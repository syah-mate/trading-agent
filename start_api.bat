@echo off
cd /d "%~dp0python"
echo ============================================
echo   FastAPI Server - Starting on port 8000
echo   Swagger UI: http://localhost:8000/docs
echo ============================================
call .\venv\Scripts\python.exe -m uvicorn api.server:app --host 0.0.0.0 --port 8000
pause
