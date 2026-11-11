@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-windows.ps1" %*
set "result=%ERRORLEVEL%"
echo.
if not "%result%"=="0" echo Installation incomplete. See the error above and install-logs.
pause
exit /b %result%
