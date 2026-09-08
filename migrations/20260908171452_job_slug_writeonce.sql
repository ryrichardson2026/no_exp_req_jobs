-- slug: the decoration in /jobs/{slug}-{internal_id}. WRITE-ONCE, same class as
-- first_seen — set on INSERT, never in the upsert's SET, operator-writable by hand.
-- Resolution matches internal_id, so a stale slug still resolves; keeping it stable
-- keeps the canonical URL stable (a changed slug would point indexed/shared links at
-- a redirect instead of a match).
alter table public.jobs add column slug text;

create or replace function public.upsert_jobs(rows jsonb, pull_ts timestamptz)
returns integer language plpgsql as $$
declare n integer;
begin
  insert into public.jobs (
    internal_id, source_id, source_job_id, dedupe_hash, schema_version,
    company_name, employer_domain, title, description_html, description_text,
    qualifications, qualifications_html, location_raw, city, state, lat, lng, market,
    employment_type, shift_raw, salary_min, salary_max, salary_is_stated, pay_period, fte,
    posted_at, apply_url, apply_class, source_class,
    source_category, source_category_method, source_function,
    experience_condition, evidence_clauses, education_flag, category, credentials,
    source_url, retrieved_at, terms_reference,
    last_seen, first_seen, slug
  )
  select
    r.internal_id, r.source_id, r.source_job_id, r.dedupe_hash, r.schema_version,
    r.company_name, r.employer_domain, r.title, r.description_html, r.description_text,
    r.qualifications, r.qualifications_html, r.location_raw, r.city, r.state, r.lat, r.lng, r.market,
    r.employment_type, r.shift_raw, r.salary_min, r.salary_max, r.salary_is_stated, r.pay_period, r.fte,
    r.posted_at, r.apply_url, r.apply_class, r.source_class,
    r.source_category, r.source_category_method, r.source_function,
    r.experience_condition, r.evidence_clauses, r.education_flag, r.category, r.credentials,
    r.source_url, r.retrieved_at, r.terms_reference,
    pull_ts, coalesce(r.first_seen, pull_ts), r.slug
  from jsonb_populate_recordset(null::public.jobs, rows) as r
  on conflict (internal_id) do update set
    source_id=excluded.source_id, source_job_id=excluded.source_job_id,
    dedupe_hash=excluded.dedupe_hash, schema_version=excluded.schema_version,
    company_name=excluded.company_name, employer_domain=excluded.employer_domain,
    title=excluded.title, description_html=excluded.description_html,
    description_text=excluded.description_text, qualifications=excluded.qualifications,
    qualifications_html=excluded.qualifications_html, location_raw=excluded.location_raw,
    city=excluded.city, state=excluded.state, lat=excluded.lat, lng=excluded.lng,
    market=excluded.market, employment_type=excluded.employment_type,
    shift_raw=excluded.shift_raw, salary_min=excluded.salary_min,
    salary_max=excluded.salary_max, salary_is_stated=excluded.salary_is_stated,
    pay_period=excluded.pay_period, fte=excluded.fte, posted_at=excluded.posted_at,
    apply_url=excluded.apply_url, apply_class=excluded.apply_class,
    source_class=excluded.source_class, source_category=excluded.source_category,
    source_category_method=excluded.source_category_method,
    source_function=excluded.source_function,
    experience_condition=excluded.experience_condition,
    evidence_clauses=excluded.evidence_clauses, education_flag=excluded.education_flag,
    category=excluded.category, credentials=excluded.credentials,
    source_url=excluded.source_url, retrieved_at=excluded.retrieved_at,
    terms_reference=excluded.terms_reference,
    last_seen=excluded.last_seen;
    -- first_seen, slug, killed, kill_* deliberately NOT updated (write-once / operator)
  get diagnostics n = row_count;
  return n;
end $$;
revoke execute on function public.upsert_jobs(jsonb, timestamptz) from public;
grant  execute on function public.upsert_jobs(jsonb, timestamptz) to service_role;

-- recreate the views so slug flows through (jobs_public via j.*, list/detail explicitly)
drop view public.jobs_list;
drop view public.jobs_detail;
drop view public.jobs_public;

create view public.jobs_public as
select j.*,
  (j.first_seen >= now() - interval '7 days') as is_new,
  case when j.posted_at is null or j.posted_at > now() then 'UNKNOWN'
       when now() - j.posted_at <= interval '7 days'  then 'FRESH'
       when now() - j.posted_at <= interval '30 days' then 'AGING'
       else 'STALE' end as freshness_state,
  coalesce(j.last_seen < (select max(p.started_at) from public.pulls p
     where p.finished_at is not null and j.source_id = any(p.sources)), false) as expired
from public.jobs j
where not j.killed
  and not exists (select 1 from public.blocklist b where
       (b.scope='internal_id'     and b.value = j.internal_id)
    or (b.scope='employer_domain' and b.value = j.employer_domain)
    or (b.scope='dedupe_hash'     and b.value = j.dedupe_hash)
    or (b.scope='title_pattern'   and j.title ~* b.value));

create view public.jobs_list as
select internal_id, slug, company_name, employer_domain, title,
       city, state, lat, lng, market, category,
       experience_condition, evidence_clauses,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, employment_type, shift_raw, fte,
       apply_url, apply_class, is_new, freshness_state, expired
from public.jobs_public;

create view public.jobs_detail as
select internal_id, slug, company_name, employer_domain, title,
       description_html, description_text, qualifications, qualifications_html,
       city, state, lat, lng, market,
       employment_type, shift_raw, fte,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, apply_url, apply_class, source_class,
       source_category, source_function,
       experience_condition, evidence_clauses, education_flag, category, credentials,
       source_url, terms_reference, is_new, freshness_state, expired
from public.jobs_public;

comment on view public.jobs_public is
  'SECURITY DEFINER deliberate: the access-control mechanism, not a leak. Anon reaches only jobs_list/jobs_detail; base tables stay RLS-locked; first_seen is unreachable by anon (enforces the sort-key prohibition). Do NOT convert to security_invoker or "fix" advisor 0010 — every row is a public job listing.';
comment on view public.jobs_list is
  'SECURITY DEFINER deliberate (see jobs_public). Anon LIST payload: no description_html, no first_seen/last_seen. Exposes slug for /jobs/{slug}-{internal_id} links.';
comment on view public.jobs_detail is
  'SECURITY DEFINER deliberate (see jobs_public). Anon job DETAIL incl description_html; no operator internals.';
grant select on public.jobs_list, public.jobs_detail to anon, authenticated;

-- clean slate: re-seed will set slug + first_seen on INSERT (both write-once)
truncate public.jobs;
truncate public.pulls restart identity;
