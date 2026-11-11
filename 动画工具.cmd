@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0animation-local\node_modules\.bin\hyperframes.cmd" (
  echo HyperFrames is missing. Run one-click installer first.
  exit /b 2
)
call "%~dp0animation-local\node_modules\.bin\hyperframes.cmd" %*
exit /b %ERRORLEVEL%
