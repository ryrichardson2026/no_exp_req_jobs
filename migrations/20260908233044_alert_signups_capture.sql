-- Capture email-alert signups — the launch signal. Anon reaches this only through the
-- capture_alert RPC; the table itself is RLS-locked with no anon policy, same discipline
-- as jobs/pulls/blocklist.
-- NOTE: the email validation here is superseded by 20260908233140_capture_alert_trim_email
-- (validate the TRIMMED email). Kept as history.
create table public.alert_signups (
  id         bigint generated always as identity primary key,
  email      text not null,
  categories text[] not null default '{}',
  location   text,
  source     text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (email)                               -- per-insert guard: one row per email
);
alter table public.alert_signups enable row level security;

create or replace function public.capture_alert(p_email text, p_categories text[], p_location text, p_source text)
returns void language plpgsql security definer set search_path = public as $$
declare valid_cats text[];
begin
  if p_email is null or p_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' then
    raise exception 'invalid email';
  end if;
  valid_cats := array(
    select unnest(coalesce(p_categories, '{}'::text[]))
    intersect
    select unnest(array['Administrative','Customer Service','Sales','Retail','Warehouse','Construction','Security','Facilities','Food Services']));
  insert into public.alert_signups (email, categories, location, source)
  values (lower(trim(p_email)), valid_cats, nullif(trim(coalesce(p_location, '')), ''), p_source)
  on conflict (email) do update
    set categories = excluded.categories, location = excluded.location,
        source = excluded.source, updated_at = now();
end $$;
revoke execute on function public.capture_alert(text, text[], text, text) from public;
grant  execute on function public.capture_alert(text, text[], text, text) to anon, authenticated;
