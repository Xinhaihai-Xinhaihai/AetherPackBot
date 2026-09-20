@echo off
setlocal
cd /d %~dp0AetherPackClient
dotnet publish -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o D:\AetherPackBot
if errorlevel 1 exit /b 1
echo.
echo [AetherPackBot] client: D:\AetherPackBot\AetherPackBot.exe
exit /b 0
