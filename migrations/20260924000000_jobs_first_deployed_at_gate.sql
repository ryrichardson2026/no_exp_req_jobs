-- Deploy-then-flip gate (applied live 2026-09-24 via Supabase apply_migration).
--
-- ROOT CAUSE it fixes: the runtime board reads jobs_list LIVE (reflects a pull the instant
-- analyze/supabase_sink.py pushes), but a job's PAGE and the edge-middleware LIVE set are frozen
-- until prerender/build.mjs bakes + `vercel deploy` ships. In run_pull._publish() the Supabase
-- push is step 1 and the deploy is the last step, non-atomic and never rolled back. So between the
-- push and the deploy (or forever, if the bake/deploy fails after a successful push) the board
-- linked to jobs whose pages didn't exist yet -> 404 ("new-job drift"). Paradox tenants
-- (Shake Shack / Sonic) surfaced it because they add jobs daily.
--
-- FIX: jobs.first_deployed_at is set ONLY after a successful deploy (analyze/mark_deployed.py,
-- driven by prerender/out/_lifecycle.json). jobs_list requires it non-null, so an undeployed
-- (or failed-deploy) job is invisible to the board -- no link, no 404. Self-heals: a job left
-- unstamped by a failed run gets stamped on the next pull's post-deploy step.

alter table public.jobs add column if not exists first_deployed_at timestamptz;

comment on column public.jobs.first_deployed_at is
  'Deploy-then-flip gate: set ONLY after a successful bake+deploy ships this job''s page (analyze.mark_deployed, driven by prerender/out/_lifecycle.json). NULL = pushed to DB but page not yet deployed. jobs_list filters IS NOT NULL so the live board never links to an unbaked job (no 404 drift). Operator-internal like first_seen/last_seen: never in the jobs_list/jobs_detail SELECT lists, only the jobs_list WHERE. Never touched by upsert_jobs (NULL on INSERT via column default).';

-- Backfill: every existing row is already deployed (the current site serves it), so stamp it so
-- nothing disappears from the board. coalesce ends in now() so the result is never null.
update public.jobs set first_deployed_at = coalesce(first_seen, last_seen, now())
  where first_deployed_at is null;

-- jobs_list gains the deploy gate by joining the base table for first_deployed_at (jobs_list is
-- SECURITY DEFINER, so it reads jobs as owner). jobs_public/jobs_detail are UNTOUCHED so the bake
-- still sees new (unstamped) rows and bakes their pages. Same 28 output columns/order as before;
-- first_deployed_at is NOT added to the SELECT list (stays unreachable by anon).
create or replace view public.jobs_list as
 select p.internal_id, p.job_number, p.slug, p.company_name, p.employer_domain, p.title,
        p.city, p.state, p.lat, p.lng, p.market, p.category, p.experience_condition,
        p.evidence_clauses, p.salary_is_stated, p.salary_min, p.salary_max, p.pay_period,
        p.posted_at, p.employment_type, p.shift_raw, p.fte, p.apply_url, p.apply_class,
        p.is_new, p.freshness_state, p.expired, p.retired
 from public.jobs_public p
 join public.jobs j on j.internal_id = p.internal_id
 where (not p.expired) and (j.first_deployed_at is not null);

comment on view public.jobs_list is
  'SECURITY DEFINER deliberate (see jobs_public). Anon LIST payload: no description_html, no first_seen/last_seen/first_deployed_at. expired/retired are derived booleans. WHERE gates on NOT expired AND first_deployed_at IS NOT NULL (deploy-then-flip: an undeployed job is invisible to the live board until analyze.mark_deployed stamps it post-deploy).';
