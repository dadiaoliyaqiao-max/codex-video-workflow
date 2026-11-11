@echo off
setlocal
cd /d "%~dp0"
node "%~dp0scripts\cover-screenshot.cjs" %*
exit /b %ERRORLEVEL%
