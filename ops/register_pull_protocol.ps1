# register_pull_protocol.ps1 - run ONCE (no admin needed) to enable the dashboard's
# "Run full pull now" button.
#
# A file:// page cannot spawn a process, so the button is instead a link to a custom URL
# protocol - noprobjobspull://run - that Windows maps to the pull wrapper. This script
# registers that protocol under HKCU (per-user, no elevation). After running it once, the
# dashboard button launches a real pull+publish in one click.
#
#   powershell -ExecutionPolicy Bypass -File ops\register_pull_protocol.ps1
#
# The first time you click the button, the browser asks "Open Windows PowerShell?" - tick
# "Always allow" and it is one-click forever after. Uninstall with -Remove.

param([switch]$Remove)

$Proj   = 'C:\Blacbar Jobs - SIte Folder\no_exp_jobs'
$Wrapper = Join-Path $Proj 'ops\run_pull_daily.ps1'
$Scheme = 'noprobjobspull'
$Root   = "HKCU:\Software\Classes\$Scheme"

if ($Remove) {
    if (Test-Path $Root) { Remove-Item $Root -Recurse -Force; Write-Host "Removed protocol '${Scheme}://'." }
    else { Write-Host "Protocol '${Scheme}://' was not registered." }
    return
}

if (-not (Test-Path $Wrapper)) { throw "Wrapper not found: $Wrapper" }

# The command Windows runs when noprobjobspull://... is opened. -Force bypasses the wrapper's
# per-day "already COMPLETE" guard so the panic button always does a fresh full pull. No %1: we
# don't need the URL passed in, and the wrapper only accepts -Force. -NoExit keeps the console
# window OPEN after the pull finishes so you can SEE the outcome (COMPLETE/PARTIAL, or a SKIP/
# error) and close it yourself - a window that auto-closes looks like "nothing happened". The
# call operator (&) runs the wrapper with -Force; run_pull.py self-gates publishing.
$ps  = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$cmd = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -NoExit -Command `"& '$Wrapper' -Force`""

$cmdKey = Join-Path $Root 'shell\open\command'
New-Item -Path $cmdKey -Force | Out-Null
Set-ItemProperty -Path $Root    -Name '(default)'    -Value 'URL:NoProbJobs Pull'
Set-ItemProperty -Path $Root    -Name 'URL Protocol' -Value ''
Set-ItemProperty -Path $cmdKey  -Name '(default)'    -Value $cmd

Write-Host ""
Write-Host "Registered protocol '${Scheme}://' -> full pull + publish (-Force)."
Write-Host "The dashboard 'Run full pull now' button is now live (approve the browser's one-time prompt)."
Write-Host "Command: $cmd"
Write-Host "Remove with:  powershell -ExecutionPolicy Bypass -File ops\register_pull_protocol.ps1 -Remove"
