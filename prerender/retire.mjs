/* Retire step — the last stage of a pull before publish:
     pull -> review -> push to Supabase -> bake -> RETIRE -> vercel deploy

   A job is "retired" 30 days after it expired (the pull stopped seeing it). The bake stops
   baking it, leaving its stale expired page on disk; this deletes that file so the route
   404s (the named 404 page). It reads out/_lifecycle.json (retired[], written by the bake)
   and removes ONLY those baked files.

   IT DELETES FILES, NEVER ROWS. The Postgres row is permanent history (churn, repost
   cycling) and is never touched here — this script has no database access at all.

   Standing rules: DRY=1 for a dry run (smoke) first; a circuit breaker aborts on 5
   consecutive or >=10% failures; progress is reported as it goes with the first error
   printed the moment it lands.

   Run: DRY=1 node retire.mjs   then   node retire.mjs */
import { readFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "out");
const DRY = !!process.env.DRY;
const MAX_CONSEC = 5, PCT = 0.10, PCT_FLOOR = 10;

const manifest = JSON.parse(await readFile(join(OUT, "_lifecycle.json"), "utf8"));
const retired = manifest.retired || [];
// only the retired records that still have a baked file on disk are real work
const targets = retired.map((p) => ({ path: p, dir: join(OUT, p.replace(/\/$/, "")) }))
  .filter((t) => existsSync(join(t.dir, "index.html")));

process.stderr.write("retire: " + retired.length + " retired records, " + targets.length
  + " with a baked file to remove" + (DRY ? "  (DRY RUN — deleting nothing)" : "") + "\n");

let removed = 0, failed = 0, consec = 0, firstError = null, aborted = null;
for (let i = 0; i < targets.length; i++) {
  const t = targets[i];
  try {
    if (!DRY) await rm(t.dir, { recursive: true, force: true });
    removed++; consec = 0;
    if (removed % 25 === 0) process.stderr.write("  removed " + removed + "/" + targets.length + "\n");
  } catch (e) {
    failed++; consec++;
    if (!firstError) { firstError = { path: t.path, error: String((e && e.message) || e) };
      process.stderr.write("  !! FIRST FAILURE " + t.path + ": " + firstError.error + "\n"); }
    if (consec >= MAX_CONSEC) { aborted = MAX_CONSEC + " consecutive failures"; break; }
    if (i + 1 >= PCT_FLOOR && failed >= (i + 1) * PCT) { aborted = "≥" + (PCT * 100) + "% of attempted removals failed"; break; }
  }
}

console.log(JSON.stringify({
  dry_run: DRY, retired_records: retired.length, had_baked_file: targets.length,
  removed, failed, aborted, first_error: firstError,
  sample: targets.slice(0, 10).map((t) => t.path),
}, null, 2));
if (failed || aborted) process.exitCode = 1;
