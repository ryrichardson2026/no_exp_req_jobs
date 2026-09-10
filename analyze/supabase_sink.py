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
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from normalize import model            # noqa: E402  stdlib-only; slugify()
APPLICABLE_PATH = os.path.join(ROOT, "out", "applicable.jsonl")

SUPABASE_URL = (os.environ.get("SUPABASE_URL")
                or "https://eyatyzatcmjnmazmaghd.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

BATCH = 150          # smaller POSTs survive flaky links better than one big body
TRIES = 5            # retry transient network/5xx with backoff; upsert is idempotent

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
    # Retry transient failures (connection reset / timeout / 5xx) with backoff. Every
    # write is an idempotent upsert or a pulls insert, so re-sending a batch is safe.
    for attempt in range(TRIES):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if 500 <= e.code < 600 and attempt < TRIES - 1:
                time.sleep(1.5 * (attempt + 1)); continue
            raise SystemExit(f"{method} {path} -> HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < TRIES - 1:
                time.sleep(1.5 * (attempt + 1)); continue
            raise SystemExit(f"{method} {path} -> network error after {TRIES} tries: {e}")


def _row(rec, pull_ts, seed):
    """Project a normalized record onto the jobs columns the pull writes."""
    row = {}
    for col in PULL_COLUMNS:
        row[col] = rec.get(col)
    row["last_seen"] = pull_ts                       # pull-managed: advances every run
    # UNCLASSIFIED is an internal sentinel, not a display category — store [] instead,
    # matching the site's contract (never emit the sentinel across the boundary).
    row["category"] = [c for c in (rec.get("category") or []) if c != "UNCLASSIFIED"]
    row["slug"] = model.slugify(rec.get("title"))    # write-once: RPC sets it on INSERT only
    if seed:
        row["first_seen"] = rec.get("first_seen")    # option A: preserve real history
    return row


GUARD_STATUS = os.path.join(ROOT, "out", "guard_status.json")


def _guard_sources():
    """{source_id: 'ok'|'skipped'|'failed'} written by run_pull's enumerate-completeness guard.
    Absent (standalone/manual run) -> every source treated as ok. Only 'ok' sources are pushed
    + reconciled; a skipped/failed source is HELD at its prior state (no last_seen advance, no
    absence increment) so a short/broken enumerate can never false-expire the board."""
    try:
        return (json.load(open(GUARD_STATUS, encoding="utf-8")) or {}).get("sources", {})
    except Exception:
        return {}


def main(argv):
    seed = "--seed" in argv
    recs = [json.loads(l) for l in open(APPLICABLE_PATH, encoding="utf-8") if l.strip()]
    guard = _guard_sources()
    ok = lambda s: guard.get(s, "ok") == "ok"
    all_sources = sorted({r.get("source_id") for r in recs if r.get("source_id")})
    push_sources = [s for s in all_sources if ok(s)]
    held = [s for s in all_sources if not ok(s)]
    push_recs = [r for r in recs if ok(r.get("source_id"))]
    pull_ts = datetime.now(timezone.utc).isoformat()

    # 1. open the pulls row — record ONLY the sources this pull actually covers (guard-passed),
    #    so a held source's coverage isn't misattributed to this pull's crawl.
    created = _req("POST", "/rest/v1/pulls",
                   body={"started_at": pull_ts, "sources": push_sources},
                   prefer="return=representation")
    pull_id = created[0]["id"]

    # 2. upsert the passed-source records via upsert_jobs. Its DO UPDATE SET names ONLY
    #    pull-managed columns, so first_seen / killed / kill_* are physically never touched
    #    (PostgREST merge-duplicates was observed to RESET omitted columns to their defaults).
    rows = [_row(r, pull_ts, seed) for r in push_recs]
    for i in range(0, len(rows), BATCH):
        _req("POST", "/rest/v1/rpc/upsert_jobs",
             body={"rows": rows[i:i + BATCH], "pull_ts": pull_ts})

    # 3. maintain the absence counter (expiry grace = absent_pulls >= 2): reset seen -> 0,
    #    increment missed -> +1, scoped to guard-PASSED sources only. Held sources untouched.
    seen_ids = [r.get("internal_id") for r in push_recs if r.get("internal_id")]
    if push_sources:
        _req("POST", "/rest/v1/rpc/reconcile_absence",
             body={"p_sources": push_sources, "p_seen_ids": seen_ids})

    # 4. close the pulls row
    _req("PATCH", "/rest/v1/pulls?id=eq." + str(pull_id),
         body={"finished_at": datetime.now(timezone.utc).isoformat(),
               "record_count": len(rows)},
         prefer="return=minimal")

    print(f"pull {pull_id} {'(SEED) ' if seed else ''}-> {len(rows)} rows upserted into jobs")
    print(f"  last_seen   {pull_ts}")
    print(f"  sources     {', '.join(push_sources)}")
    if held:
        print(f"  HELD (guard skipped/failed, prior state kept): {', '.join(held)}")
    print(f"  first_seen  {'seeded from file' if seed else 'untouched (default now() for new rows)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
