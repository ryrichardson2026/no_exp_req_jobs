# run_pull_daily.ps1 - daily recurring pull + publish for NoProbJobs.
#
# Registered as a Windows Scheduled Task (see register_pull_task.ps1). It runs
#   python run_pull.py --all --publish
# which SELF-GATES: it publishes (Supabase push -> prerender build -> retire -> vercel
# --prod) only when the run is COMPLETE. On PARTIAL - any employer's adapter failed, a
# record/density/movement halt tripped - it does NOT publish and the prior production build
# keeps serving. Per-employer failure isolation (one employer failing does not sink the
# others) is built into run_pull.py, not here.
#
# "auto-push unless fail" == publish on COMPLETE, withhold on PARTIAL. A data pull produces
# no git changes (raw/ and out/ are gitignored), so there is no git push here - the "push"
# is the Vercel production deploy that --publish performs.
#
# Secrets: SUPABASE_SERVICE_ROLE_KEY must live in .env.local (loaded below, never printed).
# The Vercel CLI must already be authenticated on this machine (vercel login, once).

param([switch]$Force)  # -Force bypasses the per-day "already COMPLETE" guard below.

$ErrorActionPreference = 'Stop'

# --- adjust these two if the layout changes ---
$Proj   = 'C:\Blacbar Jobs - SIte Folder\no_exp_jobs'
$Python = 'C:\Python314\python.exe'
# ----------------------------------------------

$LogDir = Join-Path $Proj 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log   = Join-Path $LogDir "pull_$stamp.log"
$lock  = Join-Path $LogDir '.pull.lock'
$statusFile = Join-Path $LogDir 'last_status.txt'

function Log($msg) { $line = "[{0}] {1}" -f (Get-Date -Format 's'), $msg; $line | Tee-Object -FilePath $log -Append }

# Per-day idempotency guard. The task fires from more than one trigger now - the 6am daily AND a
# logon/unlock catch-up (see register_pull_task.ps1), because this is a Modern Standby (S0) laptop
# where WakeToRun can't be trusted to wake it at 6am. Whichever trigger wins first does the day's
# run; the others must no-op. A COMPLETE run for today already in last_status.txt means we're done.
# (PARTIAL/FAIL is NOT treated as done - a catch-up trigger should get a fresh attempt.) Force a
# run regardless with -Force, e.g. after fixing a source mid-day.
if (-not $Force -and (Test-Path $statusFile)) {
    $last = (Get-Content $statusFile -Raw).Trim()
    $today = Get-Date -Format 'yyyyMMdd'
    if ($last -match "^$today\_\d{6}\s+COMPLETE") {
        Log "SKIP - today's pull already COMPLETE ($last); this trigger is a redundant catch-up"
        exit 0
    }
}

# Single-instance guard: a pull runs ~15-20 min; never let two overlap. A lock older than 3h is
# stale (a prior run died hard without cleanup) - clear it so runs don't skip forever, rather than
# blocking every future run.
if (Test-Path $lock) {
    $lockAgeH = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalHours
    if ($lockAgeH -lt 3) { Log ("SKIP - a run is already in progress ($lock, age {0:N0}m)" -f ($lockAgeH*60)); exit 0 }
    Log ("STALE LOCK ({0:N1}h old) - prior run died without cleanup; clearing it" -f $lockAgeH)
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType File -Path $lock | Out-Null

try {
    Set-Location $Proj

    # Node (build.mjs/retire.mjs) and vercel (deploy) must be resolvable under the Task
    # Scheduler environment. Augment PATH defensively with the usual install locations.
    $env:PATH = "$env:PATH;C:\Program Files\nodejs;$env:APPDATA\npm"

    # Load .env.local (KEY=VALUE lines) into the process environment. Values are never echoed.
    if (Test-Path '.env.local') {
        Get-Content '.env.local' | ForEach-Object {
            if ($_ -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
                $name = $Matches[1]
                $val  = $Matches[2].Trim().Trim('"').Trim("'")
                [Environment]::SetEnvironmentVariable($name, $val, 'Process')
            }
        }
    }

    if (-not $env:SUPABASE_SERVICE_ROLE_KEY) {
        Log "ABORT - SUPABASE_SERVICE_ROLE_KEY not set. Add it to .env.local. Nothing pulled or published."
        Set-Content $statusFile "$stamp ABORT no-key"
        exit 2
    }

    # Newest dashboard record before the run — used to detect a hard crash/kill that leaves no record.
    $runsGlob = Join-Path $Proj 'out\runs\run_*.json'
    $before = (Get-ChildItem $runsGlob -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).Name

    Log "START  python run_pull.py --all --publish"
    # Windows PowerShell 5.1 gotcha: with $ErrorActionPreference='Stop', a NATIVE process that
    # writes to stderr becomes a *terminating* NativeCommandError once its streams are merged with
    # *>&1 - which silently killed the whole pull mid-run at the first adapter that logs progress to
    # stderr (successfactors_rmk/cintas), before anything could be recorded. Drop to 'Continue' for
    # the child so its stderr flows to the log as plain text; the exit code still gates publish.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python run_pull.py --all --publish *>&1 | Tee-Object -FilePath $log -Append
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP

    # Backstop: if run_pull exited non-zero but wrote NO new dashboard record (a hard crash/kill
    # before it could emit — e.g. the task's time limit fired), record the failure ourselves so the
    # dashboard ALWAYS reflects the attempt. run_pull's own crash guard covers Python exceptions;
    # this covers the cases where the process died before any Python handler could run.
    $after = (Get-ChildItem $runsGlob -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).Name
    if ($code -ne 0 -and $after -eq $before) {
        Log "BACKSTOP  exit $code with no dashboard record - emitting a FAILED record so the run is visible"
        & $Python -m runlog --fail --reason "run_pull exited $code with no record (hard crash/kill before emit) - see logs\pull_$stamp.log" *>&1 | Tee-Object -FilePath $log -Append
    }

    if ($code -eq 0) { $status = "COMPLETE - published to production" }
    else             { $status = "PARTIAL/FAIL (exit $code) - NOT published, prior build still serving" }
    Log "END  $status"
    Set-Content $statusFile "$stamp $status"

    # Keep 30 days of logs.
    Get-ChildItem $LogDir -Filter 'pull_*.log' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force -ErrorAction SilentlyContinue

    exit $code
}
finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
