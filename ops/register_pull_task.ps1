# register_pull_task.ps1 - run ONCE to (re)create the daily scheduled task.
# Open PowerShell, then:  powershell -ExecutionPolicy Bypass -File ops\register_pull_task.ps1
# Re-running with -Force updates the existing task.

$Proj     = 'C:\Blacbar Jobs - SIte Folder\no_exp_jobs'
$Script   = Join-Path $Proj 'ops\run_pull_daily.ps1'
$TaskName = 'NoProbJobs Daily Pull'
$Time     = '6:00AM'    # 6 am Pacific — this machine's TZ is Pacific, and the task fires in
                        # local time (DST-aware), so this is 6 am PT year-round.

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""

# TWO triggers, coordinated by the per-day "already COMPLETE" guard inside run_pull_daily.ps1
# (whichever fires first runs the day's pull; the rest no-op instantly):
#
#   1. Daily 6 am — the normal path when the PC is awake at 6 am.
#   2. At logon (+10 min) — the CATCH-UP path. This is a Modern Standby (S0) laptop: it does not
#      truly sleep/wake, so WakeToRun's S3-style wake timer can't be trusted to fire the 6 am run,
#      and because S0 leaves the OS "available" the scheduler marks a missed 6 am run as permanently
#      missed (NextRun jumps to tomorrow) instead of letting StartWhenAvailable back-fill it. That is
#      exactly what happened on 2026-09-15. The logon trigger makes "run when I start/sign into the
#      machine" the reliable safety net. The 10-min delay avoids fighting boot-time resource contention.
$tDaily = New-ScheduledTaskTrigger -Daily -At $Time
$tLogon = New-ScheduledTaskTrigger -AtLogOn
$tLogon.Delay = 'PT10M'   # ISO-8601 duration: wait 10 min after logon before the catch-up run.

# StartWhenAvailable: if the PC was fully OFF at 6 am, run the missed task at next boot (catch-up).
# WakeToRun: best-effort wake if the PC is in real (S3) sleep — unreliable on this S0 machine, kept
#            only because it's harmless; the logon trigger is the actual safety net.
# AllowStartIfOnBatteries + DontStopIfGoingOnBatteries: a laptop is often on battery in the morning;
#            the old default (disallow on battery) was a second way the 6 am run got skipped.
# RunOnlyIfNetworkAvailable: skip if there is no internet.
# MultipleInstances IgnoreNew: if a trigger fires while a pull is already running, ignore it.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

# Default logon = Interactive: runs when you are logged on (screen locked / asleep is fine).
# To also run while fully LOGGED OFF, re-register with -User "$env:USERNAME" -Password (prompts),
# or flip "Run whether user is logged on or not" in the Task Scheduler UI.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $tDaily,$tLogon -Settings $settings `
    -Description 'Daily NoProbJobs pull + publish (run_pull.py --all --publish); publishes only on COMPLETE. Daily 6am + at-logon catch-up, deduped per-day inside the wrapper.' `
    -Force

# WakeToRun can only wake on battery if the power plan permits DC wake timers — disabled by default
# on this machine, so enable it in the ACTIVE plan (harmless best-effort; the logon trigger remains
# the real catch-up). AC wake timers are already enabled.
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d 1 2>$null
powercfg /setactive SCHEME_CURRENT 2>$null

Write-Host ""
Write-Host "Registered '$TaskName': daily at $Time + at-logon (+10m) catch-up."
Write-Host "Test it right now (does a real pull+publish):  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Watch the log:  Get-Content -Wait (Join-Path '$Proj' 'logs\last_status.txt')"
