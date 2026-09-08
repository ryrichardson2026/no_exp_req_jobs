-- PULLED_AT for the site's relative-date labels: the crawl date, taken from the
-- records' own retrieved_at (adapter crawl time), NOT pulls.started_at (which is when
-- the sink ran — same thing in a live pull, but they differ for a backfill). Exposes
-- only a date string to anon; jobs stays RLS-locked (definer, like the other views).
create view public.site_meta as
  select max(retrieved_at)::date::text as pulled_at from public.jobs;
comment on view public.site_meta is
  'SECURITY DEFINER deliberate (see jobs_public): exposes only the crawl date to anon; base tables stay locked. Do NOT "fix" the advisor.';
grant select on public.site_meta to anon, authenticated;
