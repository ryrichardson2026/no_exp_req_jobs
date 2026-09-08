-- New records on a later pull get first_seen = now() on INSERT, while the
-- pull-managed upsert (which omits first_seen) leaves existing rows untouched.
alter table public.jobs alter column first_seen set default now();
