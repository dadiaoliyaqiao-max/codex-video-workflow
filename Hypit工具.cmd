@echo off
setlocal
cd /d "%~dp0"
node "%~dp0hypit-local\run.cjs" %*
exit /b %ERRORLEVEL%
