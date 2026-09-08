-- Undo the kill-survival test artifact and remove the orphan open pulls left by the
-- two transient-network writer failures. Restores a clean 895-live baseline.
update public.jobs
   set killed=false, kill_reason=null, killed_at=null, killed_by=null
 where internal_id='nxj_e30c2188abf1';
delete from public.pulls where finished_at is null;
