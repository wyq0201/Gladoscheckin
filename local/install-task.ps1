# Register the "GLaDOS Checkin" scheduled task.
# ASCII only on purpose: PowerShell 5.1 mis-reads UTF-8 without BOM.
#
# Why this script exists: WorkBuddy's sandbox blocks schtasks.exe via the
# Security Center program blacklist, so the assistant cannot create the task
# on your behalf. This file is a plain Register-ScheduledTask call - run it
# yourself (install-task.bat launches it).

$ErrorActionPreference = 'Stop'

$TaskName = 'GLaDOS Checkin'
$Bat      = 'E:\workspace\my_script\Gladoscheckin\local\run.bat'
$At       = '08:40'

Write-Host '============================================'
Write-Host "  Task     : $TaskName"
Write-Host "  Schedule : daily $At"
Write-Host "  Command  : $Bat"
Write-Host '============================================'
Write-Host ''

if (-not (Test-Path -LiteralPath $Bat)) {
    Write-Host "[ERROR] run.bat not found at $Bat"
    exit 1
}

# Interactive logon type is REQUIRED: a headless / service session cannot
# render the Turnstile widget, and the check-in API answers code=5.
$action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory (Split-Path -Parent $Bat)
$trigger = New-ScheduledTaskTrigger -Daily -At $At

# StartWhenAvailable = if 08:40 was missed (PC off / asleep), run at next boot.
# WakeToRun is deliberately left OFF so the machine never wakes itself up.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 2)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description 'GLaDOS daily check-in via real Chrome (Turnstile needs a visible window). Logs: Gladoscheckin\local\logs' | Out-Null
} catch {
    Write-Host ''
    Write-Host "[FAILED] $($_.Exception.Message)"
    Write-Host '         If it mentions access denied, right-click install-task.bat'
    Write-Host '         and choose "Run as administrator".'
    exit 1
}

Write-Host '[OK] Task registered.'
Write-Host ''
Write-Host 'Run it right now to verify:'
Write-Host "    schtasks /run /tn `"$TaskName`""
Write-Host 'Then check the log folder:'
Write-Host '    E:\workspace\my_script\Gladoscheckin\local\logs\'
Write-Host ''
Write-Host 'Remove it later:'
Write-Host "    schtasks /delete /tn `"$TaskName`" /f"
