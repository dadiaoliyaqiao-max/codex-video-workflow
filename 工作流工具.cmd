@echo off
setlocal
node "%~dp0scripts\launch.cjs" %*
exit /b %errorlevel%
