"""
analyze/gone.py — write out/gone.json: the killed job URLs the bake must 410 (not 404).

Killed rows (killed=true, set by a service-role takedown) are excluded from jobs_detail, so the
bake — which reads Supabase with only the PUBLISHABLE key, and RLS hides killed rows from it —
cannot see them. It would sweep their pages and the edge would fall through to a 404. This step
reads the killed set with the SERVICE-ROLE key (the same key supabase_sink uses) and writes the
minimal fields the bake needs to build each page's 410 "gone" entry (slug, job_number, state,
city, category). build.mjs merges out/gone.json into the middleware EXPIRED (410) map, so an
intentionally-removed job returns the same "job no longer available -> get alerts" page an expired
job gets, instead of a bare 404. A missing or empty file is a no-op.

Mirrors the freshness.py -> out/freshness.json -> bake pattern: Python (service role) computes, the
bake (publishable key) consumes a local file. Runs in run_pull._publish() just before the bake.
Best-effort: any failure is logged and the existing gone.json is left untouched (last-known-good),
so a transient read error never flips a 410 back to a 404.

Config from env (never hard-code / log the service key):
    SUPABASE_URL                (optional; defaults to the project URL)
    SUPABASE_SERVICE_ROLE_KEY   (required; bypasses RLS to read killed rows)

Python stdlib only.
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out", "gone.json")

SUPABASE_URL = (os.environ.get("SUPABASE_URL")
                or "https://eyatyzatcmjnmazmaghd.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


def fetch_killed():
    """All killed rows' path-building fields, via the service-role key (RLS-bypassing)."""
    url = (SUPABASE_URL + "/rest/v1/jobs"
           "?select=slug,job_number,state,city,category&killed=is.true&order=job_number.asc")
    req = urllib.request.Request(url, headers={
        "apikey": SERVICE_KEY, "Authorization": "Bearer " + SERVICE_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    if not SERVICE_KEY:
        print("[gone] SUPABASE_SERVICE_ROLE_KEY not set — skipping (bake reads any existing gone.json)")
        return 0
    try:
        rows = fetch_killed()
    except Exception as e:
        print(f"[gone] skipped (non-fatal, kept existing gone.json): {type(e).__name__}: {e}")
        return 0
    # Keep only rows that can form a /jobs/{slug}-{job_number}/ path (jobPath needs both).
    gone = [{"slug": r.get("slug"), "job_number": r.get("job_number"),
             "state": r.get("state"), "city": r.get("city"), "category": r.get("category")}
            for r in rows if r.get("job_number") is not None and r.get("slug")]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(gone, fh, indent=2)
        fh.write("\n")
    print(f"[gone] wrote {len(gone)} killed URL(s) -> out/gone.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
