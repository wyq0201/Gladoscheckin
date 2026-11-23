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

set "NODE=C:\Users\wyq\.workbuddy\binaries\node\versions\22.22.2-6\node.exe"
if not exist "%NODE%" set "NODE=node"

if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "D=%%i"
set "LOG=logs\checkin-%D%.log"

echo ===== %date% %time% ===== >> "%LOG%"
"%NODE%" checkin.mjs %* >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === exit %RC% === >> "%LOG%"

rem Daily report: push every run, success or failure. --daily makes the
rem success path non-silent and fills the body with today's points.
"%NODE%" notify.mjs %RC% "%LOG%" --daily >> "%LOG%" 2>&1

exit /b %RC%
