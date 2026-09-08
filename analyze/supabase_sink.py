"""
analyze/supabase_sink.py - write the applicable set into Supabase (the source of truth).

This is the LAST pipeline stage in the Supabase world, replacing the jobs.js
generator. It reads out/applicable.jsonl (kept as the audited baseline until the
Supabase path is proven) and UPSERTS into public.jobs, then logs a public.pulls row.

    adapters -> normalize/enrich -> analyze/report.py (applicable.jsonl)
      -> analyze/supabase_sink.py  ->  Supabase public.jobs (+ pulls)
      -> the site reads jobs_list / jobs_detail

TWO RULES IT MUST NOT BREAK
---------------------------
1. WRITE ONLY PULL-MANAGED COLUMNS. first_seen, killed, kill_reason, killed_at,
   killed_by are never touched by a pull. This is enforced in the DB by the
   upsert_jobs RPC, whose DO UPDATE SET names only pull-managed columns — NOT by
   PostgREST's merge-duplicates, which was observed to reset omitted columns to their
   defaults (which would revive a killed listing). This is the entire reason for the
   move: a killed listing stays dead because the RPC can't touch `killed`, and
   first_seen keeps ordering what it cannot announce.

2. LOG A pulls ROW EVERY RUN. Per-source expiry depends on knowing which pull covered
   which source; the crawl date is authoritative for the site's relative labels.

first_seen (option A): the initial load runs with --seed, which INCLUDES first_seen
from the file so the real Aug-31..Sep-02 history is preserved. Every normal run OMITS
it; a genuinely new record then gets first_seen = now() from the column default.

Config from env (never hard-code the service key, never commit it, never log it):
    SUPABASE_URL                (optional; defaults to the project URL below)
    SUPABASE_SERVICE_ROLE_KEY   (required; bypasses RLS to write base tables)

Python stdlib only.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APPLICABLE_PATH = os.path.join(ROOT, "out", "applicable.jsonl")

SUPABASE_URL = (os.environ.get("SUPABASE_URL")
                or "https://eyatyzatcmjnmazmaghd.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

BATCH = 500

# The pull-managed columns the upsert sends. Deliberately EXCLUDES the operator columns
# (first_seen, killed, kill_reason, killed_at, killed_by); the upsert_jobs RPC never
# lists them in its SET, so they survive every pull. Also excludes is_new /
# freshness_state, which are not columns (the views derive them). first_seen is added
# only in --seed mode (to preserve file history); last_seen is set to the pull ts.
PULL_COLUMNS = (
    "internal_id", "source_id", "source_job_id", "dedupe_hash", "schema_version",
    "company_name", "employer_domain", "title", "description_html", "description_text",
    "qualifications", "qualifications_html",
    "location_raw", "city", "state", "lat", "lng", "market",
    "employment_type", "shift_raw", "salary_min", "salary_max", "salary_is_stated",
    "pay_period", "fte", "posted_at",
    "apply_url", "apply_class", "source_class",
    "source_category", "source_category_method", "source_function",
    "experience_condition", "evidence_clauses", "education_flag", "category", "credentials",
    "source_url", "retrieved_at", "terms_reference",
    "last_seen",
)


def _req(method, path, body=None, prefer=None):
    if not SERVICE_KEY:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY is not set in the environment. "
                 "Put it in a gitignored .env / the shell session; never in git or a "
                 "tool call. The publishable key cannot write.")
    url = SUPABASE_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SERVICE_KEY)
    req.add_header("Authorization", "Bearer " + SERVICE_KEY)
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {detail}")


def _row(rec, pull_ts, seed):
    """Project a normalized record onto the jobs columns the pull writes."""
    row = {}
    for col in PULL_COLUMNS:
        row[col] = rec.get(col)
    row["last_seen"] = pull_ts                       # pull-managed: advances every run
    # UNCLASSIFIED is an internal sentinel, not a display category — store [] instead,
    # matching the site's contract (never emit the sentinel across the boundary).
    row["category"] = [c for c in (rec.get("category") or []) if c != "UNCLASSIFIED"]
    if seed:
        row["first_seen"] = rec.get("first_seen")    # option A: preserve real history
    return row


def main(argv):
    seed = "--seed" in argv
    recs = [json.loads(l) for l in open(APPLICABLE_PATH, encoding="utf-8") if l.strip()]
    pull_ts = datetime.now(timezone.utc).isoformat()
    sources = sorted({r.get("source_id") for r in recs if r.get("source_id")})

    # 1. open the pulls row (per-source expiry + crawl date depend on this)
    created = _req("POST", "/rest/v1/pulls",
                   body={"started_at": pull_ts, "sources": sources},
                   prefer="return=representation")
    pull_id = created[0]["id"]

    # 2. upsert jobs in batches via the upsert_jobs RPC. Its DO UPDATE SET names ONLY
    #    pull-managed columns, so first_seen / killed / kill_* are physically never
    #    touched. (PostgREST's own merge-duplicates was observed to RESET omitted
    #    columns to their defaults — which would revive a killed listing — so the
    #    durable-state guarantee lives in the function, not in PostgREST semantics.)
    rows = [_row(r, pull_ts, seed) for r in recs]
    for i in range(0, len(rows), BATCH):
        _req("POST", "/rest/v1/rpc/upsert_jobs",
             body={"rows": rows[i:i + BATCH], "pull_ts": pull_ts})

    # 3. close the pulls row
    _req("PATCH", "/rest/v1/pulls?id=eq." + str(pull_id),
         body={"finished_at": datetime.now(timezone.utc).isoformat(),
               "record_count": len(rows)},
         prefer="return=minimal")

    print(f"pull {pull_id} {'(SEED) ' if seed else ''}-> {len(rows)} rows upserted into jobs")
    print(f"  last_seen   {pull_ts}")
    print(f"  sources     {', '.join(sources)}")
    print(f"  first_seen  {'seeded from file' if seed else 'untouched (default now() for new rows)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
