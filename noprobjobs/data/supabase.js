/* Read the job data from Supabase (the source of truth) via PostgREST, with the
   PUBLISHABLE key — browser-safe, and it can reach only jobs_list / jobs_detail /
   site_meta; the RLS-locked base tables are unreachable, and first_seen never crosses
   the wire. Replaces data/jobs.js: the board and landing no longer ship the whole
   record set. jobs_list omits description_html (~0.9MB for the full set vs the old
   6.6MB), and each job's description is fetched on open from jobs_detail. */
const REST = "https://eyatyzatcmjnmazmaghd.supabase.co/rest/v1";
const KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE";
const HEADERS = { apikey: KEY, Authorization: "Bearer " + KEY };

function get(path){
  return fetch(REST + path, { headers: HEADERS }).then((res) => {
    if (!res.ok) throw new Error("supabase " + path + " -> " + res.status);
    return res.json();
  });
}

/* The applicable list, no description_html. 895 < PostgREST's 1000-row default cap
   today; server-side filter/sort/pagination is a later optimization, not needed yet. */
export function listJobs(){ return get("/jobs_list?select=*&limit=2000"); }

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
  return fetch(REST + "/rpc/capture_alert", {
    method: "POST",
    headers: Object.assign({ "content-type": "application/json" }, HEADERS),
    body: JSON.stringify({ p_email: email, p_categories: categories || [], p_location: location || null, p_source: source || null }),
  }).then((res) => {
    if (!res.ok) return res.text().then((t) => { throw new Error(t || ("capture_alert " + res.status)); });
    return true;
  });
}
