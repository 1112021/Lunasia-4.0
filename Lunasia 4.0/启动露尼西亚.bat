@echo off
setlocal
cd /d "%~dp0"
title Lunasia AI Assistant

set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL%" set "POWERSHELL=powershell.exe"

"%POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" goto :done
echo.
echo Startup failed. Press any key to close this window.
pause >nul

:done
exit /b %EXIT_CODE%
