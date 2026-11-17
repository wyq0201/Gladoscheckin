@echo off
rem One-click installer for the "GLaDOS Checkin" scheduled task.
rem
rem Why this file exists: the agent sandbox blocks schtasks.exe (program
rem blacklist in WorkBuddy Security Center), so the task cannot be created
rem from the assistant side. Run this file yourself - it is a plain
rem schtasks /create call, nothing else.
rem
rem Just double-click it. If it says "access denied", right-click and pick
rem "Run as administrator".
rem
rem The task runs local\run.bat at 08:40 every day. It must run in the
rem current user session (NOT "whether user is logged on or not"): a headless
rem session cannot render the Turnstile widget, and the check-in API will
rem reject with code=5.
chcp 936 >nul
setlocal

set "TASK=GLaDOS Checkin"
set "BAT=E:\workspace\my_script\Gladoscheckin\local\run.bat"

echo ============================================
echo  Installing scheduled task: %TASK%
echo  Schedule : daily 08:40
echo  Command  : %BAT%
echo ============================================
echo.

if not exist "%BAT%" (
  echo [ERROR] run.bat not found at %BAT%
  echo         Move this file back next to run.bat and try again.
  goto :end
)

schtasks /create /tn "%TASK%" /tr "%BAT%" /sc daily /st 08:40 /f
if errorlevel 1 (
  echo.
  echo [FAILED] Could not create the task.
  echo          Most likely missing admin rights: close this window,
  echo          right-click install-task.bat, choose "Run as administrator".
  goto :end
)

echo.
echo [OK] Task created.
echo.
echo Verify it right now with:
echo     schtasks /run /tn "%TASK%"
echo then check:  E:\workspace\my_script\Gladoscheckin\local\logs\
echo.
echo Remove it later with:
echo     schtasks /delete /tn "%TASK%" /f

:end
echo.
pause
