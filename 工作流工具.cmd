@echo off
setlocal
if /I "%~1"=="install" (
  call "%~dp0一键安装并检查.cmd"
  exit /b %errorlevel%
)
node "%~dp0scripts\launch.cjs" %*
exit /b %errorlevel%
