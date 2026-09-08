-- Controlled vocabularies from normalize/model.py (outside-vocab = failure).
create type experience_condition as enum ('NONE_NEEDED','WAIVED','REQUIRED','PREFERRED','NOT_STATED');
create type pay_period    as enum ('HOURLY','DAILY','WEEKLY','MONTHLY','ANNUAL','UNKNOWN');
create type source_class  as enum ('direct-employer','aggregator','public-feed');
create type apply_class   as enum ('employer-direct','ATS','aggregator');

-- One row per pull run: authoritative crawl date + per-source expiry scope.
create table public.pulls (
  id           bigint generated always as identity primary key,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  sources      text[] not null,
  record_count int,
  notes        text
);

-- Applicable set, post cross-employer dedupe: one kept row per internal_id.
create table public.jobs (
  internal_id     text primary key,
  source_id       text not null,
  source_job_id   text not null,
  dedupe_hash     text not null,
  schema_version  text not null,
  company_name    text not null,
  employer_domain text,
  title           text not null,
  description_html text,
  description_text text,
  qualifications      text[] not null default '{}',
  qualifications_html text,
  location_raw text, city text, state text,
  lat double precision, lng double precision,
  market text,
  employment_type text, shift_raw text,
  salary_min numeric, salary_max numeric,
  salary_is_stated boolean not null default false,
  pay_period pay_period not null default 'UNKNOWN',
  fte numeric,
  posted_at timestamptz,                       -- is_new/freshness derived in views
  apply_url text, apply_class apply_class, source_class source_class,
  source_category text, source_category_method text, source_function text,
  experience_condition experience_condition,
  evidence_clauses jsonb not null default '[]',
  education_flag text,
  category text[] not null default '{}',       -- the 9; {} = uncategorised
  credentials jsonb not null default '[]',
  source_url text, retrieved_at timestamptz, terms_reference text,
  last_seen  timestamptz not null,             -- pull-managed: advances each pull
  first_seen timestamptz not null,             -- operator: write-once, never overwritten
  killed      boolean not null default false,  -- operator: manual kill, survives re-appearance
  kill_reason text, killed_at timestamptz, killed_by text,
  constraint salary_stated_needs_period check (not salary_is_stated or pay_period <> 'UNKNOWN'),
  constraint salary_order check (salary_min is null or salary_max is null or salary_min <= salary_max),
  constraint seen_order  check (first_seen <= last_seen)
);
comment on column public.jobs.first_seen is 'Write-once; the pull upsert must NOT include this in its SET list. Sort proxy only; never shipped to a display surface.';
comment on column public.jobs.killed is 'Manual kill; the pull upsert must NOT overwrite it, so a killed listing stays dead if it reappears in a later pull.';
create index jobs_category_gin on public.jobs using gin (category);
create index jobs_state_posted on public.jobs (state, posted_at desc);
create index jobs_employer     on public.jobs (employer_domain);
create index jobs_source       on public.jobs (source_id);

-- Rule-based exclusion, applied in the view (add a rule -> effect without a pull).
create table public.blocklist (
  id bigint generated always as identity primary key,
  scope text not null check (scope in ('internal_id','employer_domain','dedupe_hash','title_pattern')),
  value text not null,
  reason text, created_at timestamptz not null default now(), created_by text,
  unique (scope, value)
);

-- Lock base tables. Writes are service-role only (bypasses RLS); no anon policies.
alter table public.jobs      enable row level security;
alter table public.blocklist enable row level security;
alter table public.pulls     enable row level security;

-- Internal filtered live set (has first_seen for sorting; NOT granted to anon).
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

-- Light list payload: no description_html, no first_seen/last_seen. Anon-facing.
create view public.jobs_list as
select internal_id, company_name, employer_domain, title,
       city, state, lat, lng, market, category,
       experience_condition, evidence_clauses,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, employment_type, shift_raw, fte,
       apply_url, apply_class, is_new, freshness_state, expired
from public.jobs_public;

-- Full job detail (adds description_html/qualifications); no operator internals. Anon-facing.
create view public.jobs_detail as
select internal_id, company_name, employer_domain, title,
       description_html, description_text, qualifications, qualifications_html,
       city, state, lat, lng, market,
       employment_type, shift_raw, fte,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, apply_url, apply_class, source_class,
       source_category, source_function,
       experience_condition, evidence_clauses, education_flag, category, credentials,
       source_url, terms_reference, is_new, freshness_state, expired
from public.jobs_public;

grant select on public.jobs_list, public.jobs_detail to anon, authenticated;
