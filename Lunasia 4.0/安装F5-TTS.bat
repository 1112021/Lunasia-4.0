@echo off
setlocal
cd /d "%~dp0"
title Lunasia F5-TTS Installer

set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL%" set "POWERSHELL=powershell.exe"

"%POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_f5tts.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" echo F5-TTS is ready. Press any key to close this window.
if not "%EXIT_CODE%"=="0" echo F5-TTS installation failed. Review the message above, then try again.
pause >nul
exit /b %EXIT_CODE%
