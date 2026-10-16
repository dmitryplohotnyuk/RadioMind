@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\launch.ps1" %*
if errorlevel 1 (
  echo.
  echo RadioMind could not start. See the message above.
  pause
  exit /b 1
)
exit /b 0
