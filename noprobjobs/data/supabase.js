/* Read the job data from Supabase (the source of truth) via PostgREST, with the
   PUBLISHABLE key — browser-safe, and it can reach only jobs_list / jobs_detail /
   site_meta; the RLS-locked base tables are unreachable, and first_seen never crosses
   the wire. Replaces data/jobs.js: the board and landing no longer ship the whole
   record set. jobs_list omits description_html (~0.9MB for the full set vs the old
   6.6MB), and each job's description is fetched on open from jobs_detail. */
import { isPublished } from "./published.js";

const REST = "https://eyatyzatcmjnmazmaghd.supabase.co/rest/v1";
const KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE";
const HEADERS = { apikey: KEY, Authorization: "Bearer " + KEY };

function get(path){
  return fetch(REST + path, { headers: HEADERS }).then((res) => {
    if (!res.ok) throw new Error("supabase " + path + " -> " + res.status);
    return res.json();
  });
}

/* PostgREST caps result rows at db-max-rows (1000) regardless of ?limit=, so a single fetch
   SILENTLY truncates once a view passes 1000 rows — dropping the newest job_numbers with no
   error. jobs_list crossed ~950 and grows every pull, so page through with offset+limit until
   a short page returns. Offset paging needs a stable &order= to not skip/repeat rows. */
function getAll(path){
  const PAGE = 1000;
  const base = path.replace(/[?&]limit=\d+/i, "");
  const sep = base.includes("?") ? "&" : "?";
  const out = [];
  const step = (from) => get(base + sep + "offset=" + from + "&limit=" + PAGE).then((batch) => {
    out.push(...batch);
    return (Array.isArray(batch) && batch.length === PAGE) ? step(from + PAGE) : out;
  });
  return step(0);
}

/* The applicable list, no description_html. Paged (getAll) so it never caps at 1000.
   Filtered to the PUBLISHED set (isPublished) — jobs_list holds the WHOLE captured set
   incl. unlaunched states + suppressed employers, so without this a hard refresh showed
   the raw 2,243 while a soft click showed the filtered baked seed. Both must agree. */
export function listJobs(){ return getAll("/jobs_list?select=*&order=job_number.asc").then((rows) => rows.filter(isPublished)); }

/* One job's full detail (adds description_html), fetched when a job opens. */
export function jobDetail(internalId){
  return get("/jobs_detail?select=*&internal_id=eq." + encodeURIComponent(internalId))
    .then((rows) => rows[0] || null);
}

/* Crawl date for relative-time labels ("Posted yesterday"). */
export function pulledAt(){
  return get("/site_meta?select=pulled_at").then((rows) => (rows[0] ? rows[0].pulled_at : null));
}

/* Capture an email-alert signup — the launch signal — through the guarded capture_alert
   RPC (server-side: validates the email, whitelists categories, dedupes on email). Throws
   on a bad email or network error so the modal can show a retry rather than silently drop
   the one number that matters. */
export function captureAlert({ email, categories, location, source }){
  // Best-effort mirror to the Make automation. Fire-and-forget: Supabase is the source of truth,
  // so a Make outage must never fail the signup — hence no await and a swallowed .catch.
  notifyMake({ email, categories: categories || [], location: location || null, source: source || null });
  return fetch(REST + "/rpc/capture_alert", {
    method: "POST",
    headers: Object.assign({ "content-type": "application/json" }, HEADERS),
    body: JSON.stringify({ p_email: email, p_categories: categories || [], p_location: location || null, p_source: source || null }),
  }).then((res) => {
    if (!res.ok) return res.text().then((t) => { throw new Error(t || ("capture_alert " + res.status)); });
    return true;
  });
}

/* Make.com HTTP custom webhook — the alert-capture automation. Mirrors every signup so Make can
   drive downstream flows (email lists, notifications). Fire-and-forget by design; see captureAlert. */
const MAKE_HOOK = "https://hook.us2.make.com/o30dw0i6emep7uaurcg6lf2i5kdkg6o3";
export function notifyMake(payload){
  try {
    // application/json so Make's custom webhook parses the body into separate fields (captured_at,
    // email, categories, location, source) instead of one `value` string. This triggers a CORS
    // preflight, which the Make hook answers (Access-Control-Allow-Origin: *), so the POST delivers.
    fetch(MAKE_HOOK, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(Object.assign({ captured_at: new Date().toISOString() }, payload)),
      keepalive: true,   // let it complete even if the page navigates right after submit
    }).catch(() => {});
  } catch (e) { /* never let telemetry break capture */ }
}
