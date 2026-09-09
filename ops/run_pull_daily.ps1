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

function Log($msg) { $line = "[{0}] {1}" -f (Get-Date -Format 's'), $msg; $line | Tee-Object -FilePath $log -Append }

# Single-instance guard: a pull runs ~15-20 min; never let two overlap.
if (Test-Path $lock) { Log "SKIP - a run is already in progress ($lock)"; exit 0 }
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
        Set-Content (Join-Path $LogDir 'last_status.txt') "$stamp ABORT no-key"
        exit 2
    }

    Log "START  python run_pull.py --all --publish"
    & $Python run_pull.py --all --publish *>&1 | Tee-Object -FilePath $log -Append
    $code = $LASTEXITCODE

    if ($code -eq 0) { $status = "COMPLETE - published to production" }
    else             { $status = "PARTIAL/FAIL (exit $code) - NOT published, prior build still serving" }
    Log "END  $status"
    Set-Content (Join-Path $LogDir 'last_status.txt') "$stamp $status"

    # Keep 30 days of logs.
    Get-ChildItem $LogDir -Filter 'pull_*.log' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force -ErrorAction SilentlyContinue

    exit $code
}
finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
