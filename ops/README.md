# ops — daily recurring pull + publish

Runs `python run_pull.py --all --publish` on a schedule. It self-gates: it **publishes
only on COMPLETE** (Supabase push → prerender build → retire → `vercel --prod`). On
**PARTIAL** — any employer's adapter failed, or a record / density / movement halt tripped —
it does **not** publish and the prior production build keeps serving. One employer failing
does not sink the others (per-employer isolation lives in `run_pull.py`).

## One-time setup
1. **Add the Supabase key** to `.env.local` (gitignored, stays on this machine):
   ```
   SUPABASE_SERVICE_ROLE_KEY=<your service_role key>
   ```
   The wrapper loads it into the process env; it is never printed or committed.
2. **Vercel** must be logged in once: `vercel login` (already done on this machine).
3. **Register the task** (once):
   ```
   powershell -ExecutionPolicy Bypass -File ops\register_pull_task.ps1
   ```
4. **Test it now:** `Start-ScheduledTask -TaskName 'NoProbJobs Daily Pull'`, then check
   `logs\last_status.txt` and the newest `logs\pull_*.log`.

## Does my computer have to be on?
Task Scheduler runs on **this machine**, so:

| PC state at scheduled time | Runs? |
|---|---|
| On (even logged-off/locked, if set to run logged-off) | Yes |
| **Asleep** | Yes — the task is set with **WakeToRun** (wakes from sleep S3; laptop power plans may block wake on battery) |
| **Shut down / off** | No — but **StartWhenAvailable** runs the missed pull at the **next boot** (catch-up) |
| Hibernated | Usually no wake; catches up on resume |

So: a shut-down overnight means the pull doesn't fire at 6 AM, but it runs the next time you
power on. If you need it to fire regardless of the machine, that requires an always-on host
(a cloud runner — which we set aside because MultiCare/Allied sit behind Cloudflare and get
blocked from datacenter IPs — or leaving this PC on/asleep with WakeToRun). Pick a `$Time` in
`register_pull_task.ps1` when the machine is normally on if you want it same-day every day.

## Files
- `run_pull_daily.ps1` — the wrapper (lock, load `.env.local`, run, log, prune 30-day logs).
- `register_pull_task.ps1` — creates/updates the scheduled task (`-Force` to re-run).
- Logs land in `../logs/` (gitignored); `logs/last_status.txt` is the one-line latest result.
