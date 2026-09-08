-- Replace the ON CONFLICT upsert with explicit UPDATE + INSERT. ON CONFLICT DO UPDATE
-- calls the job_number identity's nextval for every attempted insert (even conflicts),
-- burning ~one value per existing row per pull and ballooning/gapping job numbers.
-- UPDATE-existing then INSERT-not-exists touches the sequence ONLY for real inserts, so
-- job_number stays contiguous. Write-once columns (first_seen, slug, job_number, killed,
-- kill_*) are set on INSERT and never in the UPDATE.
create or replace function public.upsert_jobs(rows jsonb, pull_ts timestamptz)
returns integer language plpgsql as $$
declare n_upd integer; n_ins integer;
begin
  update public.jobs j set
    source_id=r.source_id, source_job_id=r.source_job_id, dedupe_hash=r.dedupe_hash,
    schema_version=r.schema_version, company_name=r.company_name,
    employer_domain=r.employer_domain, title=r.title, description_html=r.description_html,
    description_text=r.description_text, qualifications=r.qualifications,
    qualifications_html=r.qualifications_html, location_raw=r.location_raw,
    city=r.city, state=r.state, lat=r.lat, lng=r.lng, market=r.market,
    employment_type=r.employment_type, shift_raw=r.shift_raw, salary_min=r.salary_min,
    salary_max=r.salary_max, salary_is_stated=r.salary_is_stated, pay_period=r.pay_period,
    fte=r.fte, posted_at=r.posted_at, apply_url=r.apply_url, apply_class=r.apply_class,
    source_class=r.source_class, source_category=r.source_category,
    source_category_method=r.source_category_method, source_function=r.source_function,
    experience_condition=r.experience_condition, evidence_clauses=r.evidence_clauses,
    education_flag=r.education_flag, category=r.category, credentials=r.credentials,
    source_url=r.source_url, retrieved_at=r.retrieved_at, terms_reference=r.terms_reference,
    last_seen=pull_ts
  from jsonb_populate_recordset(null::public.jobs, rows) r
  where j.internal_id = r.internal_id;
  get diagnostics n_upd = row_count;

  insert into public.jobs (
    internal_id, source_id, source_job_id, dedupe_hash, schema_version,
    company_name, employer_domain, title, description_html, description_text,
    qualifications, qualifications_html, location_raw, city, state, lat, lng, market,
    employment_type, shift_raw, salary_min, salary_max, salary_is_stated, pay_period, fte,
    posted_at, apply_url, apply_class, source_class,
    source_category, source_category_method, source_function,
    experience_condition, evidence_clauses, education_flag, category, credentials,
    source_url, retrieved_at, terms_reference,
    last_seen, first_seen, slug)
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
  from jsonb_populate_recordset(null::public.jobs, rows) r
  where not exists (select 1 from public.jobs j where j.internal_id = r.internal_id);
  get diagnostics n_ins = row_count;

  return n_upd + n_ins;
end $$;
revoke execute on function public.upsert_jobs(jsonb, timestamptz) from public;
grant  execute on function public.upsert_jobs(jsonb, timestamptz) to service_role;

-- reclaim the values the old ON CONFLICT burned: next new job is 896, not 1791
select setval(pg_get_serial_sequence('public.jobs','job_number'),
              (select max(job_number) from public.jobs), true);
