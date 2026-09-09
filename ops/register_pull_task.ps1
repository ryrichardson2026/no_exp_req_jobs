# register_pull_task.ps1 - run ONCE to (re)create the daily scheduled task.
# Open PowerShell, then:  powershell -ExecutionPolicy Bypass -File ops\register_pull_task.ps1
# Re-running with -Force updates the existing task.

$Proj     = 'C:\Blacbar Jobs - SIte Folder\no_exp_jobs'
$Script   = Join-Path $Proj 'ops\run_pull_daily.ps1'
$TaskName = 'NoProbJobs Daily Pull'
$Time     = '6:00AM'    # 6 am Pacific — this machine's TZ is Pacific, and the task fires in
                        # local time (DST-aware), so this is 6 am PT year-round. The PC must be
                        # on or asleep (WakeToRun) at 6 am; if off, it catches up at next boot.

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# StartWhenAvailable: if the PC was OFF at $Time, run the missed task at next boot (catch-up).
# WakeToRun: if the PC was ASLEEP at $Time, wake it and run (needs sleep S3, not shutdown;
#            on laptops the power plan may block wake on battery).
# RunOnlyIfNetworkAvailable: skip if there is no internet.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

# Default logon = Interactive: runs when you are logged on (screen locked / asleep is fine).
# To also run while fully LOGGED OFF, re-register with -User "$env:USERNAME" -Password (prompts),
# or flip "Run whether user is logged on or not" in the Task Scheduler UI.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Daily NoProbJobs pull + publish (run_pull.py --all --publish); publishes only on COMPLETE.' `
    -Force

Write-Host ""
Write-Host "Registered '$TaskName', daily at $Time."
Write-Host "Test it right now (does a real pull+publish):  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Watch the log:  Get-Content -Wait (Join-Path '$Proj' 'logs\last_status.txt')"
