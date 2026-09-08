-- The D2 prerender resolves JobPosting.jobLocation.addressCountry from an adapter-declared
-- per-source map (config/source_country.json) keyed by source_id, reading via the
-- publishable key. jobs_detail didn't expose source_id, so the country couldn't resolve and
-- jobLocation was dropped. source_id is just the adapter name (e.g. oracle_orc) — not an
-- operator internal like first_seen/killed — so it is safe to surface. Appended at the end
-- so this is a non-destructive CREATE OR REPLACE (grants and the definer property persist).
create or replace view public.jobs_detail as
select internal_id, job_number, slug, company_name, employer_domain, title,
       description_html, description_text, qualifications, qualifications_html,
       city, state, lat, lng, market,
       employment_type, shift_raw, fte,
       salary_is_stated, salary_min, salary_max, pay_period,
       posted_at, apply_url, apply_class, source_class,
       source_category, source_function,
       experience_condition, evidence_clauses, education_flag, category, credentials,
       source_url, terms_reference, is_new, freshness_state, expired,
       source_id
from public.jobs_public;
