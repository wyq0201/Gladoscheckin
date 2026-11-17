@echo off
rem GLaDOS daily check-in via real Chrome (Windows Task Scheduler entry).
rem Task name: "GLaDOS Checkin"  -  every day 08:40.
rem Why not GitHub Actions: the check-in API is behind Cloudflare Turnstile
rem (interaction-only). Pure HTTP on a datacenter IP always gets code=5.
rem A real browser on this machine passes it silently.
rem NOTE: keep rem lines ASCII-only - Chinese here gets split into commands
rem under the OEM codepage.
cd /d "%~dp0"
chcp 65001 >nul

if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "D=%%i"
set "LOG=logs\checkin-%D%.log"

echo ===== %date% %time% ===== >> "%LOG%"
"C:\Users\wyq\.workbuddy\binaries\node\versions\22.22.2-6\node.exe" checkin.mjs %* >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === exit %RC% === >> "%LOG%"

rem Push an alert on failure so unattended runs do not fail silently.
if not "%RC%"=="0" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0notify.ps1" -Code %RC% -Log "%LOG%"
)

exit /b %RC%
