@echo off
setlocal
cd /d D:\AetherPackBot
echo [Harbor] probe start
"D:\1\AstrBot\backend\python\python.exe" "D:\AetherPackBot\scripts\probe_harbor.py"
set ERR=%ERRORLEVEL%
echo.
if exist "D:\AetherPackBot\scripts\probe_harbor_result.json" (
  echo [Harbor] result: D:\AetherPackBot\scripts\probe_harbor_result.json
)
echo [Harbor] exit %ERR%
exit /b %ERR%
