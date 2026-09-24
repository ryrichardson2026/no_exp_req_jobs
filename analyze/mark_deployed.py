"""
analyze/mark_deployed.py - the deploy-then-flip stamp (last publish stage).

The runtime board reads jobs_list LIVE (reflects a pull the instant supabase_sink pushes),
but a job's PAGE and the edge-middleware LIVE set are frozen until a bake+deploy ships. So a
job pushed to the DB but not yet deployed used to show on the board with no page behind it -> 404
("new-job drift"). The gate: jobs.first_deployed_at is NULL until its page is actually deployed,
and jobs_list requires it non-null. This step sets it -- and it runs ONLY after a successful
`vercel deploy` in run_pull._publish(), so an undeployed (or failed-deploy) job stays invisible.

Source of truth for "what got deployed" is out/_lifecycle.json (written by the bake right before
the deploy): its `live` + `expired` arrays are the job pages that were baked into out/ and thus
shipped. We stamp exactly those job_numbers, and ONLY where first_deployed_at IS NULL (write-once:
never move an existing stamp).

    ... -> bake (out/_lifecycle.json + out/ pages) -> vercel deploy -> analyze.mark_deployed

Config from env (same as supabase_sink; never hard-code / log the key):
    SUPABASE_URL                (optional; defaults to the project URL)
    SUPABASE_SERVICE_ROLE_KEY   (required; bypasses RLS to write jobs.first_deployed_at)

Usage:
    python -m analyze.mark_deployed [manifest_path] [--dry-run]
    (manifest_path defaults to out/_lifecycle.json)

Python stdlib only.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from analyze.supabase_sink import _req          # noqa: E402  reuse retry/backoff + service-key guard

# The bake writes the lifecycle manifest into its deploy dir (prerender/out — the same tree
# `vercel deploy` ships), NOT the pipeline's root out/. Keep these in sync with build.mjs OUT.
DEFAULT_MANIFEST = os.path.join(ROOT, "prerender", "out", "_lifecycle.json")
CHUNK = 200          # job_numbers per PATCH — keep the in.() URL well under any length limit


def job_numbers_from_manifest(path):
    """Every baked job page's job_number, from the lifecycle manifest's live + expired arrays
    (both are baked into out/ and shipped by the deploy). Each entry is /jobs/{slug}-{num}/."""
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    nums = set()
    for key in ("live", "expired"):                     # retired pages are deleted, not shipped
        for job_path in manifest.get(key, []) or []:
            m = re.search(r"-(\d+)/?$", job_path)
            if m:
                nums.add(int(m.group(1)))
    return sorted(nums)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry-run" in argv
    manifest_path = args[0] if args else DEFAULT_MANIFEST

    if not os.path.exists(manifest_path):
        # No manifest => the bake didn't run/complete. _publish() only calls this after a clean
        # bake+deploy, so this is a loud no-op, never a silent skip that leaves jobs ungated.
        print(f"!! mark_deployed: manifest not found at {manifest_path} — nothing stamped")
        return 1

    nums = job_numbers_from_manifest(manifest_path)
    if not nums:
        print("mark_deployed: manifest has no baked job pages — nothing to stamp")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    stamped = 0
    for chunk in _chunks(nums, CHUNK):
        inlist = ",".join(str(n) for n in chunk)
        # write-once: only rows still NULL (a fresh push). Already-deployed jobs keep their stamp.
        flt = f"job_number=in.({inlist})&first_deployed_at=is.null"
        if dry:
            rows = _req("GET", f"/rest/v1/jobs?{flt}&select=job_number") or []
            stamped += len(rows)
        else:
            rows = _req("PATCH", f"/rest/v1/jobs?{flt}",
                        body={"first_deployed_at": now}, prefer="return=representation") or []
            stamped += len(rows)

    verb = "would stamp" if dry else "stamped"
    print(f"mark_deployed: {len(nums)} baked page(s) in manifest; {verb} {stamped} "
          f"newly-deployed job(s) first_deployed_at={'(dry-run)' if dry else now}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
