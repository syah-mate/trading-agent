@echo off
cd /d "%~dp0svelte"
echo ============================================
echo   SvelteKit Dashboard - Starting...
echo   http://localhost:5173
echo ============================================
call bun dev
pause
