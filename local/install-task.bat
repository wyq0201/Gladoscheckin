@echo off
rem Double-click to register the "GLaDOS Checkin" scheduled task (daily 08:40).
rem Real work lives in install-task.ps1 next to this file.
rem
rem Why a .bat shim instead of schtasks directly: WorkBuddy's sandbox blocks
rem schtasks.exe (Security Center -> Program Blacklist), so the assistant
rem cannot create the task for you. This is a plain Register-ScheduledTask
rem call, nothing else. No admin needed unless the task is owned by another
rem user. Keep every "rem" line ASCII-only - Chinese here gets split into
rem commands under the OEM codepage.
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-task.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo [exit %RC%]
pause
exit /b %RC%
