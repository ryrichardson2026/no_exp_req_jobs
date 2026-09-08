-- `retired` = a job the pull stopped seeing 30+ days ago (30 days after expiry). A
-- computed boolean in the views, exactly like `expired`: last_seen stays out of the anon
-- views (the sort-key prohibition), the view exposes only the derived answer. Drives the
-- lifecycle split: expired-recent (<30d) -> 410 + baked page; retired (>=30d) -> file
-- deleted -> 404. The Postgres row persists in every state.
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
     where p.finished_at is not null and j.source_id = any(p.sources)), false) as expired,
  ((now() - j.last_seen) > interval '30 days') as retired
from public.jobs j
where not j.killed
  and not exists (select 1 from public.blocklist b where
       (b.scope='internal_id'     and b.value = j.internal_id)
    or (b.scope='employer_domain' and b.value = j.employer_domain)
    or (b.scope='dedupe_hash'     and b.value = j.dedupe_hash)
    or (b.scope='title_pattern'   and j.title ~* b.value));

create view public.jobs_list as
select internal_id, job_number, slug, company_name, employer_domain, title,
       city, state, lat, lng, market, category,
       experience_condition, evidence_clauses,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, employment_type, shift_raw, fte,
       apply_url, apply_class, is_new, freshness_state, expired, retired
from public.jobs_public;

create view public.jobs_detail as
select internal_id, job_number, slug, company_name, employer_domain, title,
       description_html, description_text, qualifications, qualifications_html,
       city, state, lat, lng, market,
       employment_type, shift_raw, fte,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, apply_url, apply_class, source_class,
       source_category, source_function,
       experience_condition, evidence_clauses, education_flag, category, credentials,
       source_url, terms_reference, is_new, freshness_state, expired,
       source_id, retired
from public.jobs_public;

comment on view public.jobs_public is
  'SECURITY DEFINER deliberate: the access-control mechanism, not a leak. Anon reaches only jobs_list/jobs_detail; base tables stay RLS-locked; first_seen and last_seen are unreachable by anon. Do NOT "fix" advisor 0010 — every row is a public job listing.';
comment on view public.jobs_list is
  'SECURITY DEFINER deliberate (see jobs_public). Anon LIST payload: no description_html, no first_seen/last_seen. expired/retired are derived booleans, not the timestamps.';
comment on view public.jobs_detail is
  'SECURITY DEFINER deliberate (see jobs_public). Anon job DETAIL incl description_html; no operator internals. expired/retired are derived booleans.';
grant select on public.jobs_list, public.jobs_detail to anon, authenticated;
