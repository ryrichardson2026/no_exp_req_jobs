# migrations/

The Supabase schema **as code**. These `.sql` files are the reproducible record of the
database (project `eyatyzatcmjnmazmaghd`): the `jobs`/`pulls`/`blocklist` tables, the
anon-facing views, the `upsert_jobs` RPC, and the `slug` / `job_number` write-once
columns. Same discipline as `analyze/site_data.py` giving `jobs.js` a generator — if the
Supabase project is lost or a second environment is needed, the DB is rebuildable from
this directory instead of from memory.

## Naming

Files are `{version}_{name}.sql`, where `version` is the exact
`supabase_migrations.schema_migrations.version` in the live project. Keeping the original
timestamps means the Supabase CLI (`supabase db push` / `supabase migration list`) treats
already-applied migrations as applied — it will not try to re-run them against the live
project. Apply order is lexical, which is chronological.

## Replaying onto a fresh database

Apply in filename order. Two things to know:

1. **The migrations do not carry data.** They build the empty schema. After applying,
   load the applicable set with `python analyze/supabase_sink.py --seed` (needs
   `SUPABASE_SERVICE_ROLE_KEY`), which sets `first_seen`, `slug`, and `job_number` on
   insert — all write-once.
2. **A few migrations `truncate` mid-history.** `upsert_jobs_rpc` and `job_slug_writeonce`
   end with `truncate public.jobs` — they were re-test/re-seed points during the build, so
   a linear replay legitimately ends with empty tables awaiting the seed above. They are
   kept verbatim because they are the actual history; do not "clean" them.

## The one rule that keeps getting restated in these files

The three anon views are **`SECURITY DEFINER` on purpose** — that property is the
access-control mechanism (base tables stay RLS-locked; `first_seen` is unreachable by
anon). Do **not** "fix" advisor lint 0010 by converting them to `security_invoker`. Every
row they expose is a public job listing.

## Going forward

New schema changes are made with `apply_migration` against the live project **and**
committed here as a new `{version}_{name}.sql` in the same turn. The DB and this directory
must not drift.
