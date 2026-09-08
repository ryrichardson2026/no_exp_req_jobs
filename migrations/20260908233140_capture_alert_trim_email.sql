-- Trim the email BEFORE validating (real inputs carry stray leading/trailing spaces);
-- previously "Test@Example.com " was rejected. Behaviour otherwise unchanged.
create or replace function public.capture_alert(p_email text, p_categories text[], p_location text, p_source text)
returns void language plpgsql security definer set search_path = public as $$
declare valid_cats text[]; e text := lower(trim(coalesce(p_email, '')));
begin
  if e !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' then
    raise exception 'invalid email';
  end if;
  valid_cats := array(
    select unnest(coalesce(p_categories, '{}'::text[]))
    intersect
    select unnest(array['Administrative','Customer Service','Sales','Retail','Warehouse','Construction','Security','Facilities','Food Services']));
  insert into public.alert_signups (email, categories, location, source)
  values (e, valid_cats, nullif(trim(coalesce(p_location, '')), ''), p_source)
  on conflict (email) do update
    set categories = excluded.categories, location = excluded.location,
        source = excluded.source, updated_at = now();
end $$;
revoke execute on function public.capture_alert(text, text[], text, text) from public;
grant  execute on function public.capture_alert(text, text[], text, text) to anon, authenticated;
