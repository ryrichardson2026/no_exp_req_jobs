-- Explicit upsert: the DO UPDATE SET names ONLY pull-managed columns, so first_seen,
-- killed, kill_reason, killed_at, killed_by are physically never updated by a pull —
-- the durable-state guarantee (a killed listing stays dead) no longer depends on
-- PostgREST's column-omission behaviour, which was observed to RESET omitted columns.
-- On insert, first_seen = the sent value (seed preserves file history) or the pull
-- timestamp (a brand-new record is first seen now) — never now(), so first_seen <= last_seen.
-- SECURITY INVOKER (default): only service_role may execute it (see revoke/grant), and
-- service_role bypasses RLS, so no SECURITY DEFINER and no extra advisor finding.
--
-- NOTE: superseded by 20260908174836_upsert_jobs_no_seq_waste (this ON CONFLICT form
-- burns the job_number identity sequence on every conflict). Kept as history.
create or replace function public.upsert_jobs(rows jsonb, pull_ts timestamptz)
returns integer
language plpgsql
as $$
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
    last_seen, first_seen
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
    pull_ts, coalesce(r.first_seen, pull_ts)
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
  get diagnostics n = row_count;
  return n;
end $$;

revoke execute on function public.upsert_jobs(jsonb, timestamptz) from public;
grant  execute on function public.upsert_jobs(jsonb, timestamptz) to service_role;

-- clean slate for the re-test
truncate public.jobs;
truncate public.pulls restart identity;
