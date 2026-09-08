comment on view public.jobs_public is
  'SECURITY DEFINER is DELIBERATE — it is the access-control mechanism, not a leak. Anon reaches only jobs_list/jobs_detail; base tables stay RLS-locked with no anon policy; first_seen is physically unreachable by any anon query, enforcing the sort-key prohibition (normalize/sort_key.py) at the DB layer. Do NOT convert to security_invoker or "fix" the security_definer_view advisor (lint 0010): every row is a public job listing, and the invoker alternative (RLS + per-column grants on jobs) has a worse failure mode — a mistake exposes base columns instead of hiding them.';

comment on view public.jobs_list is
  'SECURITY DEFINER is DELIBERATE (see jobs_public). Anon-facing light LIST payload: no description_html, no first_seen/last_seen. Do NOT "fix" the security_definer_view advisor — the definer property is what hides those columns from anon.';

comment on view public.jobs_detail is
  'SECURITY DEFINER is DELIBERATE (see jobs_public). Anon-facing full job DETAIL incl description_html; excludes operator internals (first_seen/last_seen/killed/kill_*). Do NOT "fix" the security_definer_view advisor.';
