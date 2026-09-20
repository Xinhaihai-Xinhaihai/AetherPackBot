@echo off
setlocal
title AetherPackBot
cd /d D:\AetherPackBot

set PYTHON=D:\1\AstrBot\backend\python\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo ============================================
echo   AetherPackBot  Harbor + Brain
echo   web  http://127.0.0.1:7619
echo   cwd  %CD%
echo   py   %PYTHON%
echo ============================================

"%PYTHON%" main.py %*
set ERR=%ERRORLEVEL%
echo.
echo [AetherPackBot] exit %ERR%
pause
exit /b %ERR%
