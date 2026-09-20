@echo off
setlocal
cd /d D:\AetherPackBot
echo [AnyRouter] checkin
"D:\1\AstrBot\backend\python\python.exe" "D:\AetherPackBot\scripts\anyrouter_checkin.py"
exit /b %ERRORLEVEL%
