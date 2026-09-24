-- Correct the initial backfill in 20260924000000_jobs_first_deployed_at_gate.sql (applied live
-- 2026-09-24). That backfill stamped EVERY existing row so the board wouldn't blank during the
-- change, which over-stamped unlaunched-state jobs (LAUNCHED_STATES = {WA}; any other state is
-- never baked and 404s). Those rows sat in jobs_list hidden only by the CLIENT-side isPublished
-- filter (noprobjobs/data/published.js). Null them so first_deployed_at means what it says (page
-- actually deployed) and jobs_list excludes them at the DB level too -- defense-in-depth so the
-- board never depends on the client filter to hide a dead page.
--
-- Board is UNAFFECTED: every nulled row is non-WA, which the client already hid (jobs_list went
-- 2182 -> 1276 = exactly the WA/null-state set the board was already showing).
--
-- Durable: mark_deployed only stamps baked (launched-state) pages from prerender/out/_lifecycle
-- .json, and upsert_jobs never touches first_deployed_at, so a re-seen unlaunched job (an employer
-- that still pulls TX) stays NULL and out of jobs_list. When a state launches, add it to
-- LAUNCHED_STATES; its jobs then bake and mark_deployed stamps them into jobs_list.

update public.jobs
   set first_deployed_at = null
 where state is not null and state <> 'WA';
