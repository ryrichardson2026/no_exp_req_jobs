/* THE published-set rule, in ONE place — imported by BOTH the static bake
   (prerender/build.mjs) and the runtime data layer (data/supabase.js).

   Why this file exists: the bake filters the baked SEED, but the board also fetches
   jobs_list DIRECTLY from Supabase on a hard load / refresh (see supabase.listJobs).
   Supabase holds the WHOLE captured set (all states incl the unlaunched ones, and
   suppressed employers), so without applying the SAME filter at runtime, a refresh
   showed 2,243 jobs (raw jobs_list) while a soft click showed 1,309 (the filtered
   seed). Both paths must agree — so the predicate lives here and both import it.

   Keep in lockstep with the pull/enrich side; this is the LAST gate before display. */

// The only LAUNCHED states — an allowlist, not a denylist (a denylist let geo-scope
// leaks like a Chipotle CA job publish). To launch a state, add its code here.
export const LAUNCHED_STATES = new Set(["WA"]);

// Whole employers pulled from the published surface, keyed by employer_domain.
export const SUPPRESSED_EMPLOYERS = new Set(["providence.org", "dollargeneral.com"]);

/* A record is published iff its state is launched (null tolerated — those are legit
   in-scope WA records whose state field failed to parse) AND its employer isn't
   suppressed. */
export function isPublished(r){
  return (r.state == null || LAUNCHED_STATES.has(r.state))
      && !SUPPRESSED_EMPLOYERS.has(r.employer_domain);
}
