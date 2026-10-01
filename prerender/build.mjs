/* D2 full build — bake every route to static HTML. A rebuild accompanies every pull.

   Routes (all knowable from the data):
     /jobs/{slug}-{job_number}/   one per job          JobPosting JSON-LD (live jobs only)
     /jobs/                       all-jobs index        no JSON-LD
     /{state}/                    per state present     no JSON-LD
     /{state}/{category}/         per category present  no JSON-LD
     /                            landing               no JSON-LD

   JSON-LD is emitted only on a LIVE job page: an expired job (the pull removed it) shows
   "no longer accepting applications", so a JobPosting there would contradict the page
   (markup–page parity). Reads Supabase via the publishable key. Baked mobile-first.

   Run: npm run build   (from prerender/) */
import { createServer } from "node:http";
import { readFile, writeFile, mkdir, stat, rm, cp, copyFile, readdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { jobPostingLd, jobPostingScript } from "../noprobjobs/data/jobPosting.js";
import { jobPath, browsePath, CAT_SLUG, STATE_SLUG, backTo } from "../noprobjobs/data/routes.js";
import { LAUNCHED_STATES, SUPPRESSED_EMPLOYERS, isPublished } from "../noprobjobs/data/published.js";
import * as PM from "../noprobjobs/data/pageMeta.js";
import * as R from "../noprobjobs/data/record.js";
import { ALERT_PAGES, ALERT_MARKETS, pagesForMarket, marketIndexPath } from "../noprobjobs/data/alertPages.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const OUT = join(HERE, "out");
// Incremental bake: a job page's HTML is a pure function of its record + is_new + JSON-LD + the
// shared template. We hash those, and skip re-rendering (in headless Chrome) any job page whose
// hash AND the template version match the last successful bake and whose file still exists. Browse
// + landing routes aggregate the whole set (only ~16, cheap) so they ALWAYS render. Manifest lives
// in prerender/ (NOT out/, so it isn't deployed) and persists across runs. BAKE_FULL=1 forces a
// full rebake (ignore the manifest). Missing/corrupt manifest or a changed template => full rebake
// (fail-safe = current behavior). Cost then scales with churn, not total inventory.
const MANIFEST_PATH = join(HERE, ".bake-manifest.json");
const BAKE_FULL = process.env.BAKE_FULL === "1" || process.env.BAKE_FULL === "true";
const sha1 = (s) => createHash("sha1").update(s).digest("hex");
// Template version = a hash of EVERY file that affects a rendered page: build.mjs itself + all
// js/mjs/html/css under noprobjobs/ (board.js, landing.js, data/*, ui/*, styles.css, the HTML
// shells, vendor React). Any change here invalidates every per-page hash -> a full rebake, so a
// template edit can never ship a stale mix of old + new pages. Computed AFTER logos.js/cap.js are
// regenerated so a logo/config change is included.
async function computeTemplateVersion(){
  const h = createHash("sha1");
  h.update(readFileSync(join(HERE, "build.mjs")));
  const walk = async (dir) => {
    for (const ent of (await readdir(dir, { withFileTypes: true })).sort((a, b) => (a.name < b.name ? -1 : 1))) {
      const p = join(dir, ent.name);
      if (ent.isDirectory()) await walk(p);
      else if (/\.(js|mjs|html|css)$/.test(ent.name)) { h.update(ent.name); h.update(await readFile(p)); }
    }
  };
  await walk(SITE);
  return h.digest("hex");
}
const COUNTRY = JSON.parse(readFileSync(join(HERE, "..", "config", "source_country.json"), "utf8"));
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const REST = "https://eyatyzatcmjnmazmaghd.supabase.co/rest/v1";
const KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE";
const PORT = 8795;
const CONC = Number(process.env.BAKE_CONC) || 6;    // concurrent Chrome pages (BAKE_CONC lowers it on machines where 6 crashes Chrome mid-bake)
const SITE_URL = (process.env.SITE_URL || "https://noprobjobs.com").replace(/\/$/, "");   // canonical + OG + sitemap base

// The published-set rule (LAUNCHED_STATES allowlist + SUPPRESSED_EMPLOYERS + isPublished) is
// imported from ../noprobjobs/data/published.js — the SAME module the runtime board imports, so
// the baked seed and the live jobs_list fetch can never disagree (they did: a refresh showed the
// raw 2,243 while a click showed the filtered seed). See that file for the full rationale
// (allowlist-not-denylist, null-state tolerance, Providence suppression). To launch a state or
// suppress an employer, edit THAT file — this bake and the runtime both pick it up.
const MOBILE = { width: 412, height: 915, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
// Change #2: the Washington lander — a landing-page clone (served from index.html, so it runs
// landing.js) that differs only in its headline. Baked as its own route; excluded from the
// state-browse machinery entirely (no filtering, no state param). Trailing slash to match how
// every other baked route is written and how trailingSlash serves it.
const WA_LANDER = "/washington-jobs/";
// Alert-signup guide pages + a per-market index hub. The page list is the shared registry in
// noprobjobs/data/alertPages.js (also read by the WA lander's guides section + the footer), so a new
// page or geo touches one file. Baked from alerts.html (→ alerts.js); live slice inlined by serve().
const ALERTS = ALERT_PAGES;
const ALERT_PATHS = [...ALERT_PAGES.map((p) => p.path), ...Object.keys(ALERT_MARKETS).map(marketIndexPath)];

// board category -> its alert-lander path (the "guide" hub for that category). Drives the
// lander cross-links, the job-page "See all {category} jobs" link, and the breadcrumb category
// level. Healthcare is an employer-scoped SECTOR page but carries the "Healthcare" category tag
// (tenant_category add), so map it by that tag. Categories with no lander (Administrative,
// Customer Service, Government, Construction) fall back to the browse page where used.
const LANDER_BY_CAT = {};
for (const p of ALERT_PAGES) {
  const cat = p.category || (p.slug === "healthcare" ? "Healthcare" : null);
  if (cat) LANDER_BY_CAT[cat] = p.path;
}
// category page URL for a job: its lander if one exists, else the state/category browse page.
const catPageUrl = (state, cat) => LANDER_BY_CAT[cat] || browsePath(state, cat);

// BreadcrumbList JSON-LD for a job page: Home > {Category} jobs > {Job title}. The category
// level points at the job's category hub (lander if one exists, else the browse page) — real
// crawlable ancestry AND a Google rich-result type. Omits the category level when the job has
// no board category (or one with no hub), so no item ever points at a dead URL.
function breadcrumbLd(r){
  const items = [{ name: "No-Experience Jobs", url: SITE_URL + "/" }];
  const cat = (r.category || [])[0];
  if (cat && (LANDER_BY_CAT[cat] || CAT_SLUG[cat])) {
    const label = (cat === "Transportation/Automotive" ? "Transportation" : cat) + " Jobs";
    items.push({ name: label, url: SITE_URL + catPageUrl(r.state, cat) });
  }
  items.push({ name: r.title || "Job", url: SITE_URL + jobPath(r) + "/" });
  const ld = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({ "@type": "ListItem", position: i + 1, name: it.name, item: it.url })),
  };
  return '<script type="application/ld+json">\n' + JSON.stringify(ld, null, 2).replace(/</g, "\\u003c") + "\n</script>";
}

// Live data for one /alerts/{market}/{category}/ page, computed from the published jobs_list the
// SAME way the listing view derives it: "applicable" = the board's default exp facets (none +
// preferred, i.e. R.expFacet != null), scoped to the market (state or null-state) and category.
// Inlined by serve() so the page bakes with real content and the runtime needs no query.
function alertSlice(list, entry, pulledAt){
  const { state, category, employers } = entry;
  const applicable = (r) => R.expFacet(r.experience_condition) != null;
  const inMarket = (r) => r.state === state || r.state == null;
  // Category pages scope by the job's category tag; a SECTOR page (e.g. Healthcare — not a board
  // category) scopes by employer_domain instead. `listBase` is where the per-employer links point.
  const inScope = employers ? (r) => employers.indexOf(r.employer_domain) >= 0 : (r) => R.recordCats(r).indexOf(category) >= 0;
  const slice = list.filter((r) => inMarket(r) && applicable(r) && inScope(r));
  const listBase = employers ? ("/" + STATE_SLUG[state] + "/") : browsePath(state, category);

  // highest employer-STATED hourly rate, floored to a whole dollar so "up to $X" never overstates.
  let maxPay = null;
  for (const r of slice) if (r.salary_is_stated && r.pay_period === "HOURLY") {
    const v = r.salary_max || r.salary_min || 0;
    if (v > 0 && (maxPay == null || v > maxPay)) maxPay = v;
  }
  if (maxPay != null) maxPay = Math.floor(maxPay);

  // Newest first: prefer the baked eff_new_date recency (the landing "recent" key), backfill by
  // newestFirst. `recent` = the 6 featured cards; `openings` = the next ~24 as a compact static
  // <a href> list — SEO crawl equity to job pages + a substantial listing, not just a signup form.
  const dated = slice.filter((r) => r.eff_new_date).sort((a, b) =>
    a.eff_new_date < b.eff_new_date ? 1 : (a.eff_new_date > b.eff_new_date ? -1 : String(a.internal_id).localeCompare(String(b.internal_id))));
  const undated = slice.filter((r) => !r.eff_new_date).sort(R.newestFirst);
  const sorted = dated.concat(undated);
  const recent = sorted.slice(0, 6);
  const openings = sorted.slice(6, 30).map((r) => ({ t: r.title, c: r.city, s: r.state, h: jobPath(r) + "/" }));

  // top employers by open count; each links to the listing view pre-filtered to them (?emp=slug).
  const byCo = {};
  for (const r of slice) {
    const key = R.employerSlug(r.company_name);
    if (!key) continue;
    (byCo[key] = byCo[key] || { company: R.companyLabel(r.company_name), slug: key, count: 0 }).count++;
  }
  const whosHiring = Object.values(byCo).sort((a, b) => b.count - a.count || a.company.localeCompare(b.company)).slice(0, 6)
    .map((e) => ({ company: e.company, count: e.count, href: listBase + "?emp=" + e.slug }));

  // other categories in this market with live applicable jobs, current one excluded.
  const marketApplicable = list.filter((r) => inMarket(r) && applicable(r));
  const catCount = {};
  for (const r of marketApplicable) for (const c of R.recordCats(r)) if (CAT_SLUG[c]) catCount[c] = (catCount[c] || 0) + 1;
  const otherCats = Object.keys(catCount).filter((c) => c !== category)
    .sort((a, b) => catCount[b] - catCount[a] || a.localeCompare(b))
    .map((c) => ({ label: c, displayLabel: c === "Transportation/Automotive" ? "Transportation" : c, count: catCount[c], href: browsePath(state, c), landerHref: LANDER_BY_CAT[c] || null }));

  // seasonal signal (content says "if any"): title/employment_type mentions seasonal or holiday.
  const seasonalCount = slice.filter((r) => /seasonal|holiday/i.test(r.title || "") || /seasonal/i.test(r.employment_type || "")).length;

  return { count: slice.length, maxPay, recent, openings, whosHiring, otherCats, seasonalCount, pulledAt: pulledAt || null };
}

// Logo-carousel brand list for /about/ and /partners/ ("See jobs from employers like:"). Every
// file in repo-root logos/ EXCEPT aboutusimage.png. Shake Shack / Jimmy John's / Walmart are gated
// on live feed presence (only shown if that employer has jobs in `list` right now). Display names
// come from CAROUSEL_NAMES, with a hyphens->words title-case fallback for any future file.
const CAROUSEL_NAMES = {
  "TJ-Maxx.png": "TJ Maxx", "allied-universal.png": "Allied Universal", "fred-meyer.png": "Fred Meyer",
  "homegoods.jpg": "HomeGoods", "marshalls.png": "Marshalls", "ontrac.png": "OnTrac",
  "providence.png": "Providence", "quality-food-centers.jpg": "Quality Food Centers", "sierra.png": "Sierra",
  "u-haul.jpg": "U-Haul", "Walmart.png": "Walmart", "target.jpg": "Target", "king-county.png": "King County",
  "Shake-Shack.png": "Shake Shack", "Jimmy-Johns.png": "Jimmy John's",
};
async function carouselBrands(list){
  const dir = join(HERE, "..", "logos");
  let files = [];
  try { files = await readdir(dir); } catch { files = []; }
  const OKEXT = new Set([".png", ".jpg", ".jpeg", ".svg", ".webp"]);
  const GATED = { "Shake-Shack.png": "shakeshack.com", "Jimmy-Johns.png": "jimmyjohns.com", "Walmart.png": "walmart.com" };
  const has = (dom) => list.some((r) => r.employer_domain === dom);
  const titleCase = (f) => f.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const out = [];
  for (const f of files.sort()) {
    if (f === "aboutusimage.png") continue;
    if (!OKEXT.has(extname(f).toLowerCase())) continue;
    if (GATED[f] && !has(GATED[f])) continue;
    out.push({ name: CAROUSEL_NAMES[f] || titleCase(f), file: f });
  }
  return out;
}
const MIME = { ".html":"text/html",".js":"text/javascript",".mjs":"text/javascript",".css":"text/css",
  ".json":"application/json",".svg":"image/svg+xml",".png":"image/png",".ico":"image/x-icon",".woff2":"font/woff2",".map":"application/json" };

// Scripts the SOURCE html declares (vendor React + the app entry). Anything ELSE present in the
// DOM after the bake was injected at prerender time by GTM (gtm.js/gtag, Clarity, any future tag)
// and must not ship baked — the inline GTM loader re-injects whatever's needed on the client.
// Snapshotting the source's own <script src> set (rather than blocklisting one vendor domain)
// generalizes to any tag. Inline scripts (the GTM loader, the __npj_* data blobs) have no src and
// are always kept. Filled in main() before baking; see the strip in bake().
let KEEP_SRCS = [];
function sourceScriptSrcs(){
  const srcs = new Set();
  for (const f of ["index.html", "board.html"]) {
    try { for (const m of readFileSync(join(SITE, f), "utf8").matchAll(/<script[^>]+\bsrc="([^"]+)"/g)) srcs.add(m[1]); }
    catch { /* file absent -> contributes nothing */ }
  }
  return [...srcs];
}

const WAIT = {
  // Job page = board chrome + seeded panel + skeleton list. The panel's description renders as
  // TWO nested [data-desc-html] (jobPage wrapper + describe.js output) only once jobs_detail has
  // resolved during the bake; the loading skeleton is a single wrapper. So >=2 means "the real
  // description is in", regardless of its length. The list stays a skeleton — not waited on.
  job: "document.querySelectorAll('[data-desc-html]').length >= 2 && !!document.querySelector('h1')",
  browse: "document.querySelectorAll(\"[role='list'] > *\").length > 0",
  landing: "document.getElementById('root') && document.getElementById('root').children.length > 0",
  alerts: "document.getElementById('root') && document.getElementById('root').children.length > 0",
  static: "document.getElementById('root') && document.getElementById('root').children.length > 0",
};

function serve(cache){
  return createServer(async (req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    try {
      if (p !== "/" && existsSync(join(SITE, p)) && (await stat(join(SITE, p))).isFile()) {
        res.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" });
        return res.end(await readFile(join(SITE, p)));
      }
      // Alert-signup pages (/alerts/{market}/{category}/) are their own SPA (alerts.html →
      // alerts.js) with the live slice inlined as __npj_data BEFORE boot. The page has no Supabase
      // fetch, so (unlike the landing) it must render from the blob during the bake — like a job page.
      const alertData = cache && cache.alertsByPath && cache.alertsByPath[p.replace(/\/+$/, "") + "/"];
      if (alertData) {
        let ah = await readFile(join(SITE, "alerts.html"), "utf8");
        const blob = JSON.stringify(alertData).replace(/</g, "\\u003c");
        ah = ah.replace("</body>", '<script id="__npj_data" type="application/json">' + blob + "</script></body>");
        res.writeHead(200, { "content-type": "text/html" });
        return res.end(ah);
      }
      // Static content pages (/about/, /partners/) are their own SPA (pages.html → pages.js) with
      // their content/brand-list inlined as __npj_data, same pattern as the alert pages.
      const staticData = cache && cache.staticByPath && cache.staticByPath[p.replace(/\/+$/, "") + "/"];
      if (staticData) {
        let ph = await readFile(join(SITE, "pages.html"), "utf8");
        const blob = JSON.stringify(staticData).replace(/</g, "\\u003c");
        ph = ph.replace("</body>", '<script id="__npj_data" type="application/json">' + blob + "</script></body>");
        res.writeHead(200, { "content-type": "text/html" });
        return res.end(ph);
      }
      // "/" and the Washington lander are the landing SPA (index.html → landing.js); every
      // other virtual path is the board SPA (board.html → board.js).
      const isLanding = p === "/" || p.replace(/\/+$/, "") === WA_LANDER.replace(/\/+$/, "");
      let html = await readFile(join(SITE, isLanding ? "index.html" : "board.html"), "utf8");
      if (isLanding && cache) {
        // Inline the landing blob (jobs list + pulledAt + employer-carousel brands) BEFORE serving,
        // so the bake-time prerender renders the recent jobs AND the logo carousel from it (the
        // carousel brand list is only known here, not from the runtime jobs_list fetch). Same blob
        // the runtime reads, so baked and hydrated DOM match.
        const lblob = JSON.stringify({ list: JSON.parse(cache.list), pulledAt: cache.pulledAt || null, brands: cache.carouselBrands || [] }).replace(/</g, "\\u003c");
        html = html.replace("</body>", '<script id="__npj_data" type="application/json">' + lblob + "</script></body>");
      }
      // A job route (/jobs/{slug}-{num}) inlines its panel-seed blob BEFORE the app boots, so the
      // bake paints the panel (chrome + panel + skeleton list) — attachCache withholds jobs_list
      // for job routes, so the list stays a skeleton. Same blob the runtime page ships.
      const jm = !isLanding && cache && /-(\d+)\/?$/.exec(p);
      if (jm && cache.blobByNum[jm[1]]) {
        const blob = JSON.stringify({ job: cache.blobByNum[jm[1]], pulledAt: cache.pulledAt || null }).replace(/</g, "\\u003c");
        html = html.replace("</body>", '<script id="__npj_job" type="application/json">' + blob + "</script></body>");
      } else if (!isLanding && cache && cache.jobsSeed && p.replace(/\/+$/, "") === "/jobs") {
        // /jobs/ browse: the desktop board auto-opens the newest no-experience job (derive()'s
        // pageRecs[0]) and, without a seeded detail, paints a loading skeleton then swaps in the
        // description once jobs_detail resolves — a large layout shift (~0.12 CLS on desktop cold
        // load). Inline that job's FULL detail so the panel renders its real description on the
        // first frame (board.js seeds state.details from this blob), no skeleton, no swap.
        const blob = JSON.stringify({ detail: cache.jobsSeed }).replace(/</g, "\\u003c");
        html = html.replace("</body>", '<script id="__npj_jobs_seed" type="application/json">' + blob + "</script></body>");
      }
      res.writeHead(200, { "content-type": "text/html" });
      res.end(html);
    } catch (e) { res.writeHead(500); res.end(String(e)); }
  });
}

// A transient PostgREST/DB blip (5xx) or rate-limit (429) on ANY single page otherwise aborts the
// WHOLE bake — one jobs_detail 500 killed a publish 2026-09-21. Retry those with linear backoff; a
// real 4xx (or exhausted tries) still returns/throws so a genuine error fails loud, never silent.
async function fetchRetry(url, opts, tries = 4){
  let resp, err;
  for (let i = 0; i < tries; i++){
    try {
      resp = await fetch(url, opts);
      if (resp.ok || (resp.status !== 429 && resp.status < 500)) return resp;  // ok, or a real non-retryable 4xx
    } catch (e) { err = e; resp = null; }                                      // network error — retryable
    if (i < tries - 1) await new Promise((res) => setTimeout(res, 500 * (i + 1)));
  }
  if (resp) return resp;   // exhausted on 5xx/429 — hand back the last response; caller throws on !ok
  throw err;               // exhausted on network errors — rethrow the last one
}

async function fetchAll(path){
  // PostgREST caps result rows at db-max-rows (1000 here) regardless of ?limit=, so a single
  // fetch SILENTLY truncates once a view exceeds 1000 rows (jobs_detail hit 1086 after U-Haul
  // onboarded). The dropped rows were the newest job_numbers, so their /jobs/{slug} pages were
  // never baked and served the "gone" fallback while live. Page through with offset+limit until
  // a short page returns. Callers must supply a stable &order= (offset paging is unstable
  // otherwise); paths that can't (single-row meta) simply return on the first short page.
  const PAGE = 1000;
  const base = path.replace(/[?&]limit=\d+/i, "");          // our paging owns the window
  const sep = base.includes("?") ? "&" : "?";
  const out = [];
  for (let from = 0; ; from += PAGE) {
    const r = await fetchRetry(REST + base + sep + "offset=" + from + "&limit=" + PAGE, { headers: { apikey: KEY, Authorization: "Bearer " + KEY } });
    if (!r.ok) throw new Error(path + " -> " + r.status);
    const batch = await r.json();
    out.push(...batch);
    if (!Array.isArray(batch) || batch.length < PAGE) break;
  }
  return out;
}

// Authoritative row count, INDEPENDENT of how many rows a fetch returned. `count=exact` puts
// the true total in Content-Range (".../N") even with limit=1, so it catches a truncated
// fetchAll that would otherwise pass silently (the 1000-cap that shipped 1000 of 1086 jobs).
async function countExact(view){
  const r = await fetchRetry(REST + view + "?select=job_number&limit=1", { headers: { apikey: KEY, Authorization: "Bearer " + KEY, Prefer: "count=exact" } });
  if (!r.ok && r.status !== 206) throw new Error(view + " count -> " + r.status);
  const total = parseInt(((r.headers.get("content-range") || "").split("/")[1] || ""), 10);
  return Number.isFinite(total) ? total : null;
}

async function writeBaked(routePath, html){
  const dir = join(OUT, routePath.replace(/\/$/, ""));
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "index.html"), html, "utf8");
}

// Vercel Edge Middleware (self-contained, no imports so it bundles as a plain edge fn):
// job lifecycle at the edge. expired -> 410 + a message and a route back; retired/unknown
// job URL -> the named 404; live -> fall through to the baked static page.
function middlewareSource(expiredBack, live){
  const head = "// Generated by prerender/build.mjs — do not edit. Job lifecycle at the edge.\n"
    + "const EXPIRED = " + JSON.stringify(expiredBack) + ";\n"
    + "const LIVE = new Set(" + JSON.stringify(live) + ");\n"
    + "export const config = { matcher: '/jobs/:path*' };\n";
  const body = [
    "function gone(info){",
    "  var back = info.back || '/jobs/';",
    "  var q = 'alerts=1' + (info.cat ? '&cat=' + encodeURIComponent(info.cat) : '') + (info.city ? '&city=' + encodeURIComponent(info.city) : '');",
    "  var alertsUrl = back + (back.indexOf('?') < 0 ? '?' : '&') + q;",
    "  return '<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">'",
    "    + '<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">'",
    "    + '<title>Job no longer available — NoProbJobs.com</title>'",
    "    + '<style>body{font-family:system-ui,-apple-system,\"Segoe UI\",sans-serif;background:#f7f9fc;margin:0;color:#132a4a}main{max-width:560px;margin:0 auto;padding:72px 22px}.badge{display:inline-block;padding:4px 10px;border-radius:3px;background:#c8102e;color:#fff;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}h1{font-size:30px;line-height:1.14;margin:18px 0 10px;letter-spacing:-.01em}p{font-size:16.5px;line-height:1.6;color:#5a6b83;margin:0 0 22px;max-width:46ch}a.cta{display:inline-flex;align-items:center;min-height:46px;padding:0 20px;border-radius:3px;background:#c8102e;color:#fff;text-decoration:none;font-weight:700;font-size:15.5px}a.alt{display:inline-block;margin-left:14px;color:#132a4a;font-weight:600;font-size:15px}</style>'",
    "    + '</head><body><main><span class=\"badge\">No experience needed</span>'",
    "    + '<h1>Unfortunately, this job is no longer available.</h1>'",
    "    + '<p>Sign up for job alerts and we\\'ll email you when similar jobs are posted.</p>'",
    "    + '<a class=\"cta\" href=\"' + alertsUrl + '\">Get job alerts</a>'",
    "    + '<a class=\"alt\" href=\"' + back + '\">Browse more jobs</a>'",
    "    + '</main></body></html>';",
    "}",
    "export default async function middleware(request){",
    "  const { pathname } = new URL(request.url);",
    "  const p = pathname.endsWith('/') ? pathname : pathname + '/';",
    "  if (!/^\\/jobs\\/.+-\\d+\\/$/.test(p)) return;                 // not a job detail page -> static",
    "  const info = EXPIRED[p];",
    "  if (info) return new Response(gone(info), { status: 410, headers: { 'content-type': 'text/html; charset=utf-8' } });",
    "  if (LIVE.has(p)) return;                                       // live -> baked static page",
    "  const r = await fetch(new URL('/404.html', request.url));     // retired/unknown -> named 404",
    "  return new Response(r.body, { status: 404, headers: { 'content-type': 'text/html; charset=utf-8' } });",
    "}",
    "",
  ].join("\n");
  return head + body;
}

// Assemble a complete deployable static site in out/: baked pages + SPA assets + sitemap
// (live URLs only) + vercel.json + the edge middleware. Idempotent, so a targeted rebake
// still leaves out/ deployable. The baked landing owns out/index.html, so it is NOT copied.
async function assembleDeploy(live, expiredBack, browse, lastmod = {}){
  for (const f of ["board.html", "board.js", "landing.js", "alerts.js", "pages.js", "styles.css", "404.html",
                   "favicon.ico", "icon-192.png", "apple-touch-icon.png", "og.png", "logo.png"]) await copyFile(join(SITE, f), join(OUT, f));
  for (const d of ["data", "ui", "vendor"]) await cp(join(SITE, d), join(OUT, d), { recursive: true });
  // Hand-picked brand logos live at repo-root logos/ (the user's drop folder), served from
  // /logos/ in the deploy. Same-origin, so no CSP host to allow. Cosmetic progressive
  // enhancement — skipped during bake (like favicons), copied here for the live site.
  if (existsSync(join(HERE, "..", "logos"))) await cp(join(HERE, "..", "logos"), join(OUT, "logos"), { recursive: true });

  const base = SITE_URL;
  const locs = ["/", WA_LANDER, "/about/", "/partners/", ...ALERT_PATHS, ...browse, ...live];   // change #2: lander in sitemap; alert pages added; expired/retired excluded
  // <lastmod> (W3C YYYY-MM-DD) is the one optional tag Google actually uses (changefreq/priority
  // are ignored). Values come from `lastmod` (built by the caller): a job's stated posted_at
  // (stable — a job page's baked content doesn't change after posting), and the pull date for the
  // list/landing/browse pages that genuinely change every pull. Omitted when we have no honest
  // date, rather than fabricating "modified today" (which Google distrusts).
  // Filename is sitemap-jobs.xml, NOT the conventional sitemap.xml: Search Console left the
  // apex sitemap.xml stuck (submitted, never processed) despite it being valid and 200-ing.
  // Resubmitting under a fresh URL is the standard way to force GSC to re-fetch from scratch.
  // Served as a static file in out/, so Vercel returns it before any SPA rewrite (like robots.txt).
  const SITEMAP = "sitemap-jobs.xml";
  const xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + locs.map((u) => { const lm = lastmod[u];
        return "  <url><loc>" + base + u + "</loc>" + (lm ? "<lastmod>" + lm + "</lastmod>" : "") + "</url>"; }).join("\n")
    + "\n</urlset>\n";
  await writeFile(join(OUT, SITEMAP), xml, "utf8");
  // The bake is incremental (no rm(OUT)), so a sitemap.xml from a prior bake would linger and
  // ship frozen. Remove it: GSC seeing the old URL 404 helps it drop the stuck entry, and it
  // leaves sitemap-jobs.xml as the single source of truth.
  await rm(join(OUT, "sitemap.xml"), { force: true });

  // robots.txt — allow all + declare the sitemap. Written as a real file so Vercel serves it as
  // text/plain (its default for .txt), NOT routed through the SPA. Was missing (404) before.
  await writeFile(join(OUT, "robots.txt"),
    "User-agent: *\nAllow: /\nSitemap: " + base + "/" + SITEMAP + "\n", "utf8");

  // Unbaked browse routes (empty categories, jobless states) fall back to the SPA. Two
  // explicit rules — state root and sub-path with an unnamed (.*) wildcard — matching the
  // form proven in D1; a single "/:state/:rest*" did not match sub-paths on Vercel. Baked
  // pages are static files, which Vercel serves before any rewrite, so only truly-unbaked
  // browse paths reach these. /jobs/* is handled by the middleware, not here.
  // destination is /board/ (NOT /board.html): with cleanUrls+trailingSlash, /board.html
  // 308-redirects to /board/, and a rewrite whose destination redirects fails to 404.
  const states = Object.values(STATE_SLUG).join("|");
  const apex = base.replace(/^https?:\/\//, "");   // "noprobjobs.com"
  const vercel = { cleanUrls: true, trailingSlash: true,
    // Canonicalize the host: www.* -> apex (https). (http -> https is automatic on Vercel.) So
    // Search Console's host checks and the sitemap resolve to one canonical origin, never a 404.
    redirects: [
      { source: "/:path*", has: [{ type: "host", value: "www." + apex }],
        destination: base + "/:path*", permanent: true },
    ],
    rewrites: [
      { source: "/:state(" + states + ")", destination: "/board/" },
      { source: "/:state(" + states + ")/(.*)", destination: "/board/" },
    ] };
  await writeFile(join(OUT, "vercel.json"), JSON.stringify(vercel, null, 2), "utf8");
  await writeFile(join(OUT, "middleware.js"), middlewareSource(expiredBack, live), "utf8");
  return { sitemap_urls: locs.length };
}

async function bake(page, route, cache){
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await page.goto(route.url, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForFunction(WAIT[route.type], { timeout: 20000 });
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      if (route.ld) {
        await page.evaluate((html) => {
          const t = document.createElement("template"); t.innerHTML = html.trim();
          document.head.appendChild(t.content.firstChild);
        }, route.ld);
      }
      if (route.crumbLd) {
        await page.evaluate((html) => {
          const t = document.createElement("template"); t.innerHTML = html.trim();
          document.head.appendChild(t.content.firstChild);
        }, route.crumbLd);
      }
      // Per-page metadata. Browse counts come from the rendered "N jobs found" on the page
      // (same source as displayed, never recomputed). Sets <title>, injects meta/canonical/
      // OG/favicon, and absolutizes the ItemList item urls the board rendered relative.
      let meta = route.meta;
      if (route.type === "browse") {
        const n = await page.evaluate(() => { const m = (document.body.textContent || "").match(/([\d,]+)\s+jobs?\s+found/i); return m ? m[1].replace(/,/g, "") : ""; });
        meta = route.state
          ? (route.category
              ? { title: PM.categoryTitle(route.category, route.state), description: PM.categoryDescription(route.category, route.state, n) }
              : { title: PM.stateTitle(route.state), description: PM.stateDescription(route.state, n) })
          : { title: "Get Hired Now - No Experience Needed | NoProbJobs", description: n + " jobs hiring now, no experience required. No sign-up, no resume, free to apply." };
      }
      if (meta) {
        const canonical = SITE_URL + route.path;
        const headHtml = PM.metaHead({ title: meta.title, description: meta.description, canonical, ogImage: SITE_URL + "/og.png" });
        await page.evaluate((title, head, base) => {
          document.title = title;
          const t = document.createElement("template"); t.innerHTML = head;
          document.head.appendChild(t.content);
          document.querySelectorAll('meta[itemprop="url"]').forEach((m) => { if (m.content && m.content.charAt(0) === "/") m.content = base + m.content; });
        }, meta.title, headHtml, SITE_URL);
      }
      const html = await page.evaluate((keep) => {
        // Strip every EXTERNAL script the source didn't declare — i.e. everything GTM injected
        // during the prerender (gtm.js/gtag AND Clarity, and any future tag). The inline GTM
        // loader (no src) survives and re-injects on the client, so GTM never double-fires and no
        // vendor tag ships baked. Snapshot of the source's own scripts is passed in from Node.
        const KEEP = new Set(keep);
        document.querySelectorAll('script[src]').forEach((el) => { if (!KEEP.has(el.getAttribute('src'))) el.remove(); });
        // The non-blocking font link (rel=preload as=style onload→stylesheet) has its onload
        // fire DURING the bake, so it serializes as a render-blocking rel="stylesheet". Reset
        // it to rel="preload" so the baked HTML ships non-blocking; the client's onload
        // re-activates it. Without this the bake silently defeats the font de-block (item 6).
        document.querySelectorAll('link[as="style"][rel="stylesheet"]').forEach((el) => { el.rel = "preload"; });
        return "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
      }, KEEP_SRCS);
      // Landing pages ship their data INLINE so the client renders from it with no Supabase
      // query (drops the ~2.8s critical-path call and the freshCount/R.today() flash). The blob
      // is the same jobs_list the bake rendered from, so baked and hydrated DOM stay identical.
      let out = html;
      // (Landing __npj_data is now inlined at SERVE time above, so it's already in the rendered
      // DOM and the bake-time prerender uses it — no post-render injection needed here.)
      // Internal-link mesh: append the related-jobs <nav> just before </body> (a sibling of the
      // SPA root, so hydration never touches it and the links ship in the raw baked HTML).
      if (route.type === "job" && route.related) {
        out = out.replace("</body>", route.related + "</body>");
      } else if (route.hubIndex) {
        // Browse/landing hubs: inject the full crawlable job-link index (same sibling-of-#root,
        // hidden-but-present-in-raw-HTML technique as the related mesh above).
        out = out.replace("</body>", route.hubIndex + "</body>");
      }
      await writeBaked(route.path, out);
      return { path: route.path, type: route.type, bytes: Buffer.byteLength(out, "utf8"), ld: !!route.ld };
    } catch (e) {
      if (attempt === 1) return { path: route.path, type: route.type, error: String(e && e.message || e) };
    }
  }
}

// Serve Supabase reads from a one-time cache via request interception: without this,
// every one of the 895 standalone pages re-fetches the full jobs_list (~0.9MB) from
// Supabase (~800MB + rate-limit risk). Logo favicons are progressive enhancement (async,
// cosmetic, no baked content) and are skipped so the bake is fast and deterministic.
const CORS = { "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,OPTIONS",
  "access-control-allow-headers": "authorization,apikey,content-type,x-client-info,accept-profile,content-profile,prefer,range",
  "access-control-max-age": "86400" };

function attachCache(page, cache){
  return page.setRequestInterception(true).then(() => {
    page.on("request", (req) => {
      const u = req.url();
      if (u.includes("/rest/v1/")) {
        // The SPA sends an Authorization header, so the browser fires a CORS preflight.
        // Answer OPTIONS with the CORS headers (not a body), or the real GET never fires.
        if (req.method() === "OPTIONS") return req.respond({ status: 204, headers: CORS });
        // On a JOB route the list must bake as a SKELETON, so leave its jobs_list fetch pending
        // (never respond) — recs stays null → skeleton. The panel is seeded from the inlined blob
        // (serve()), and the description from jobs_detail below, so the page still bakes fully.
        // The pending request is discarded when the page navigates to the next route.
        if (u.includes("/jobs_list") && /\/jobs\/.+-\d+\/?$/.test(page.url())) return;   // job route only, NOT the /jobs/ browse list
        let body = "[]";
        if (u.includes("/jobs_list")) body = cache.list;
        else if (u.includes("/site_meta")) body = cache.meta;
        else if (u.includes("/jobs_detail")) {
          const mi = /internal_id=eq\.([^&]+)/.exec(u), mn = /job_number=eq\.(\d+)/.exec(u);
          const rec = mi ? cache.byId[decodeURIComponent(mi[1])] : (mn ? cache.byNum[mn[1]] : null);
          body = JSON.stringify(rec ? [rec] : []);
        }
        return req.respond({ status: 200, headers: Object.assign({ "content-type": "application/json" }, CORS), body });
      }
      if (/google\.com\/s2\/favicons/.test(u)) return req.abort();
      // Block GTM during the bake. If gtm.js executes, the container fires its tags (Clarity's
      // Custom HTML, gtag, any future tag) and they get serialized into the static HTML — Clarity
      // injects an INLINE bootstrap a src-only strip can't catch. Blocking here means no tag runs
      // at prerender, so nothing third-party bakes in; the inline GTM loader still ships and
      // re-injects everything once on the client. (The dead <script src=gtm.js> the loader appends
      // before this abort is removed by the source-snapshot strip in bake().)
      if (/googletagmanager\.com/.test(u)) return req.abort();
      return req.continue();
    });
  });
}

// Regenerate noprobjobs/data/logos.js from the files in repo-root logos/. The runtime
// resolver (data/record.js localLogo) reads this map to show a hand-picked brand mark
// keyed on the brand slug (the file's basename), overriding the domain favicon. Adding a
// logo is one action: drop <slug>.<png|jpg|svg> into logos/ — this rebuild picks it up.
async function generateLogoIndex(){
  const dir = join(HERE, "..", "logos");
  let files = [];
  try { files = await readdir(dir); } catch { files = []; }
  const OKEXT = new Set([".png", ".jpg", ".jpeg", ".svg", ".webp"]);
  const map = {};
  for (const f of files.sort()) {
    const ext = extname(f).toLowerCase();
    if (!OKEXT.has(ext)) continue;
    map[f.slice(0, -ext.length).toLowerCase()] = f;      // basename IS the brand slug
  }
  const body = "/* GENERATED by prerender/build.mjs — do not hand-edit. Scanned from repo-root\n"
    + "   logos/. Maps a brand slug (see brandSlug in record.js) to its logo filename so the\n"
    + "   runtime knows the file + extension. Add a logo: drop <slug>.<png|jpg|svg> into logos/. */\n"
    + "export const LOGOS = " + JSON.stringify(map, null, 2) + ";\n";
  await writeFile(join(SITE, "data", "logos.js"), body, "utf8");
  return Object.keys(map);
}

// Regenerate noprobjobs/data/cap.js from config/listing.json. board.js derive() imports
// EMPLOYER_CAP and hands it to record.js spreadByEmployer to spread employers across each
// listing page. Committed like logos.js (it ships to the static deploy and is present at
// both bake and runtime). Tune the cap by editing config/listing.json and re-baking —
// no code change. Missing/partial config falls back to the shipped default.
async function generateCapConfig(){
  let cfg = {};
  try { cfg = JSON.parse(readFileSync(join(HERE, "..", "config", "listing.json"), "utf8")); } catch { cfg = {}; }
  const cap = (cfg && cfg.employer_cap) || { key: "tenant", n: 3, scope: "page" };
  const body = "/* GENERATED by prerender/build.mjs — do not hand-edit. Sourced from\n"
    + "   config/listing.json. Per-employer spread cap for listing views; the reorder\n"
    + "   itself is spreadByEmployer in data/record.js. Tune via config/listing.json + re-bake. */\n"
    + "export const EMPLOYER_CAP = " + JSON.stringify(cap, null, 2) + ";\n";
  await writeFile(join(SITE, "data", "cap.js"), body, "utf8");
  return cap;
}

async function main(){
  const t0 = Date.now();
  KEEP_SRCS = sourceScriptSrcs();
  process.stderr.write("  bake keeps source scripts: [" + KEEP_SRCS.join(", ") + "]\n");
  const logoSlugs = await generateLogoIndex();
  process.stderr.write("  logo index: " + logoSlugs.length + " brand logo(s) [" + logoSlugs.join(", ") + "]\n");
  const cap = await generateCapConfig();
  process.stderr.write("  employer cap: " + cap.n + " per " + cap.key + " per " + cap.scope + "\n");
  const LIMIT = process.env.LIMIT ? +process.env.LIMIT : 0;                 // LIMIT=N: bake first N jobs
  const ONLY = process.env.ONLY ? process.env.ONLY.split(",").map((s) => s.trim()) : null;  // ONLY=n,m: bake just these job_numbers
  const SMOKE = 8;                                                          // jobs in the smoke pass
  const fullRun = !LIMIT && !ONLY;
  // The bake is INCREMENTAL — no rm(OUT). A job that crosses 30 days stops being baked
  // (skipped below), and its stale expired page stays on disk until retire.mjs deletes it;
  // that is the retire step's real work. Paths are stable (slug + job_number are write-once),
  // so live/expired pages just overwrite and nothing orphans.
  // Full fetch first — coverage (see the manifest below) is asserted against these lengths, so it
  // verifies the DB PULL, not the published subset. Then suppress unlaunched states from the site.
  const recsFetched = await fetchAll("/jobs_detail?select=*&order=job_number.asc");   // &order= = stable offset paging
  const listFetched = await fetchAll("/jobs_list?select=*&order=job_number.asc");
  const recs = recsFetched.filter(isPublished);
  const list = listFetched.filter(isPublished);
  // Merge the ONE recency computation (analyze/freshness.py -> out/freshness.json) onto every
  // list record, OVERWRITING the view's is_new (now unread — the rule lives in one Python call
  // site, never a raw-field recompute on a surface). The card reads r.is_new. Missing file =>
  // no badges + a loud warning, never a silent wrong value.
  const freshPath = join(HERE, "..", "out", "freshness.json");
  if (!existsSync(freshPath)) console.warn("!! out/freshness.json missing — run `python -m analyze.freshness` before the bake; New badges will be OFF");
  const freshJson = existsSync(freshPath) ? JSON.parse(readFileSync(freshPath, "utf8")) : {};
  const freshMap = freshJson.is_new || {};
  const effMap = freshJson.eff_new_date || {};   // effective recency date (ISO|null) — the landing "recent" sort key
  for (const r of list) { r.is_new = !!freshMap[r.internal_id]; r.eff_new_date = effMap[r.internal_id] || null; }
  const meta = await fetchAll("/site_meta?select=pulled_at");
  const jobsTotal = await countExact("/jobs_detail");   // authoritative — asserted against the fetch below
  const listTotal = await countExact("/jobs_list");
  const cache = { list: JSON.stringify(list), meta: JSON.stringify(meta), byId: {}, byNum: {}, blobByNum: {}, pulledAt: (meta[0] && meta[0].pulled_at) || null };
  for (const r of recs) {
    cache.byId[r.internal_id] = r; cache.byNum[String(r.job_number)] = r;
    // blobByNum = each job's panel-seed record, from jobs_detail so it covers EVERY job incl.
    // expired ones (jobs_list omits expired — an expired /jobs page must still seed its panel).
    // Strip the big description/qualifications HTML so the inlined blob stays small (the panel's
    // description comes from the baked DOM, not this blob).
    const { description_html, description_text, qualifications_html, qualifications, ...slim } = r;
    cache.blobByNum[String(r.job_number)] = slim;
  }

  // Panel-seed for the /jobs/ browse route: the job the desktop board auto-opens on a cold load.
  // Must match derive()'s pageRecs[0] EXACTLY — over jobs_list (the board's `all`), default
  // filters leave only the no-experience gate active (exps=["none"]), sorted "newest". Take its
  // FULL jobs_detail row (with description_html) so board.js can seed state.details and paint the
  // real description on the first frame — see the __npj_jobs_seed injection in serve().
  {
    const seedRow = list.filter((r) => R.expFacet(r.experience_condition) === "none").slice().sort(R.newestFirst)[0];
    const seedDetail = seedRow ? cache.byId[seedRow.internal_id] : null;
    cache.jobsSeed = seedDetail || null;
  }

  // ---- Internal-link mesh (SEO crawlability) ----
  // Every job page gets a static <a href> block linking to sibling LIVE jobs in the same primary
  // category, arranged as a RING by job_number: coverage is complete (every job both GIVES and
  // RECEIVES up to K inbound links) and stable (a new job appends to the ring, it doesn't
  // reshuffle it). This is the fix for "Discovered - currently not indexed": a sitemap-only page
  // with no internal links reads to Google as low-priority. Plain navigation anchors only - NO
  // per-job markup here (that would be the list-page-carries-JobPosting violation). Built from the
  // LIVE subset of recs (never links an expired/410 page); injected before </body> below, a sibling
  // of the SPA root, so it survives client hydration AND is in the raw HTML Google reads.
  const REL_K = 8;
  const relCity = (s) => { const raw = String(s || "").trim().replace(/\s+/g, " "); return (raw && raw === raw.toUpperCase()) ? raw.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase()) : raw; };
  const relEsc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  const relByNum = {};
  {
    const byCat = {};
    for (const r of recs) { if (r.expired || r.retired) continue; const c = (r.category || [])[0] || "_uncat"; (byCat[c] = byCat[c] || []).push(r); }
    for (const c of Object.keys(byCat)) {
      const arr = byCat[c].slice().sort((a, b) => a.job_number - b.job_number);
      const N = arr.length;
      if (N < 2) continue;
      const landerHref = LANDER_BY_CAT[c];
      const catLabel = c === "Transportation/Automotive" ? "Transportation" : c;
      const seeAll = landerHref ? '<a class="npj-related-all" href="' + landerHref + '">See all ' + relEsc(catLabel) + " jobs in WA</a>" : "";
      for (let i = 0; i < N; i++) {
        const picks = [];
        for (let j = 1; j <= Math.min(REL_K, N - 1); j++) picks.push(arr[(i + j) % N]);
        const li = picks.map((o) => {
          const loc = [relCity(o.city), o.state].filter(Boolean).join(", ");
          return '<li><a href="' + jobPath(o) + '/">' + relEsc(o.title) + (loc ? " — " + relEsc(loc) : "") + "</a></li>";
        }).join("");
        relByNum[String(arr[i].job_number)] = '<nav class="npj-related" aria-label="Related jobs"><h2>More no-experience jobs</h2><ul>' + li + "</ul>" + seeAll + "</nav>";
      }
    }
  }

  // ---- Hub crawl index (SEO crawlability) ----
  // A full, crawlable <ul> of every LIVE job under each hub (all-jobs /jobs/, per-state, per-
  // category) plus the two landers, injected before </body> exactly like the related-jobs mesh:
  // a sibling of the SPA root, so hydration never touches it and the <a href>s ship in the raw
  // baked HTML. Hidden via .npj-hub-index (same rationale as .npj-related). This gives the
  // INDEXED hub/home pages a direct crawlable path to the WHOLE corpus — the fix for job pages
  // stuck at "Discovered - currently not indexed" with no inbound internal links. Built from
  // `list` (published + live; never an expired/410 page), sorted by job_number for stable output.
  const hubNav = (records, label) => {
    const arr = records.slice().sort((a, b) => a.job_number - b.job_number);
    if (!arr.length) return null;
    const li = arr.map((o) => {
      const loc = [relCity(o.city), o.state].filter(Boolean).join(", ");
      return '<li><a href="' + jobPath(o) + '/">' + relEsc(o.title) + (loc ? " — " + relEsc(loc) : "") + "</a></li>";
    }).join("");
    return '<nav class="npj-hub-index" aria-label="' + relEsc(label) + '"><ul>' + li + "</ul></nav>";
  };

  // enumerate routes
  const routes = [];
  let ldCount = 0, expiredCount = 0, retiredCount = 0, jjLdDropped = 0;
  // Batch 1 H: drop JobPosting JSON-LD on Jimmy John's (Paradox) records whose posted_at is more
  // than a year stale — Paradox emits unreliable 2019-2023 dates, and a JobPosting with a years-old
  // datePosted is misleading structured data Google can distrust. Removes ONLY the <script> block;
  // the page HTML, its sitemap entry, and the board card are unchanged. Scoped tight (source +
  // employer + stale date) so no other tenant is touched.
  const jjCutoff = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
  const staleJJ = (r) => r.source_id === "paradox" && /jimmy\s*john/i.test(r.company_name || "")
    && /^\d{4}-\d{2}-\d{2}/.test(String(r.posted_at || "")) && String(r.posted_at).slice(0, 10) < jjCutoff;
  for (const r of recs) {
    if (r.retired) { retiredCount++; continue; }                              // retired -> not baked; retire.mjs removes any stale file
    const dropLd = r.expired || staleJJ(r);                                   // expired: markup-page parity; staleJJ: unreliable datePosted
    const ld = dropLd ? null : jobPostingScript(jobPostingLd(r, COUNTRY));
    if (staleJJ(r) && !r.expired) jjLdDropped++;
    if (r.expired) expiredCount++; if (ld) ldCount++;
    routes.push({ type: "job", path: jobPath(r) + "/", url: null, ld, num: r.job_number,
      related: relByNum[String(r.job_number)] || null,
      crumbLd: r.expired ? null : breadcrumbLd(r),
      meta: { title: PM.jobTitle(r), description: PM.jobDescription(r) } });
  }
  // browse: states present, and categories present within each state. state/category ride
  // on the route so bake() can build the title; the count comes from the rendered page.
  const byState = {};
  // Build from `list` (published + live + applicable; jobs_list omits expired), NOT `recs` (which
  // includes expired/410 job rows). A category present only on an expired/suppressed record would
  // emit a browse route that renders EMPTY, and the browse bake waits for >=1 list item
  // (WAIT.browse) -> 20s timeout -> smoke-test abort (WA x construction, 0 live jobs, did exactly
  // this). Empty browse routes are meant to stay UNBAKED and fall back to the SPA (see below).
  for (const r of list) { if (!r.state) continue; (byState[r.state] = byState[r.state] || new Set()); (r.category || []).forEach((c) => byState[r.state].add(c)); }

  // Hub cross-links: a crawlable map from EVERY hub/landing page to all the OTHER hubs (the all-
  // jobs index, each state hub, and every category hub that has live jobs). Fixes the orphaned
  // category hubs (6 of 12 had zero inbound links — sitemap-only) and gives the indexed homepage a
  // one-hop path to every hub, so crawl can flow homepage -> hub -> jobs. Prepended to each hub's
  // job index below; same hidden .npj-hub-index block, present in the raw baked HTML.
  const hubCrossLinks = (() => {
    const items = ['<li><a href="/jobs/">All jobs</a></li>'];
    for (const st of Object.keys(byState)) {
      items.push('<li><a href="' + browsePath(st, null) + '">All jobs in ' + relEsc(st) + "</a></li>");
      for (const c of [...byState[st]].sort()) if (CAT_SLUG[c])
        items.push('<li><a href="' + browsePath(st, c) + '">' + relEsc(c) + " jobs in " + relEsc(st) + "</a></li>");
    }
    return '<nav class="npj-hub-index" aria-label="Browse all job hubs"><ul>' + items.join("") + "</ul></nav>";
  })();

  const browsePaths = new Set(["/jobs/"]);
  routes.push({ type: "browse", path: "/jobs/", url: null, state: null, category: null, hubIndex: hubCrossLinks + hubNav(list, "All jobs") });
  for (const st of Object.keys(byState)) {
    const sp = browsePath(st, null); browsePaths.add(sp);
    routes.push({ type: "browse", path: sp, url: null, state: st, category: null, hubIndex: hubCrossLinks + hubNav(list.filter((r) => r.state === st), "All jobs in " + st) });
    for (const c of byState[st]) if (CAT_SLUG[c]) { const cp = browsePath(st, c); browsePaths.add(cp); routes.push({ type: "browse", path: cp, url: null, state: st, category: c, hubIndex: hubCrossLinks + hubNav(list.filter((r) => r.state === st && (r.category || []).includes(c)), c + " jobs in " + st) }); }
  }
  routes.push({ type: "landing", path: "/", url: null, hubIndex: hubCrossLinks + hubNav(list, "All jobs"), meta: { title: PM.landingTitle(), description: PM.landingDescription() } });
  // Change #2: Washington lander. Same landing type (same render wait + meta injection), its
  // own path so bake() writes out/washington-jobs/index.html and sets canonical to itself.
  routes.push({ type: "landing", path: WA_LANDER, url: null, hubIndex: hubCrossLinks + hubNav(list.filter((r) => r.state === "WA"), "All jobs in WA"), meta: { title: PM.waLanderTitle(), description: PM.waLanderDescription() } });
  // Alert-signup pages: compute each page's live slice, stash it for serve() to inline as
  // __npj_data, and register the route (baked as its own type; alerts.html shell + alerts.js).
  cache.alertsByPath = {};
  for (const a of ALERTS) {
    cache.alertsByPath[a.path] = alertSlice(list, a, cache.pulledAt);
    routes.push({ type: "alerts", path: a.path, url: null, meta: { title: a.title, description: a.description } });
  }
  // Per-market index hub (/alerts/{market}/) — the guides grid with live counts; the footer links here.
  for (const ms of Object.keys(ALERT_MARKETS)) {
    const mk = ALERT_MARKETS[ms];
    const guides = pagesForMarket(ms).map((p) => ({ label: p.label, iconCat: p.iconCat || null, path: p.path, count: (cache.alertsByPath[p.path] || {}).count || 0 }));
    cache.alertsByPath[marketIndexPath(ms)] = { kind: "index", marketSlug: ms, marketName: mk.name, guides, pulledAt: cache.pulledAt || null };
    routes.push({ type: "alerts", path: marketIndexPath(ms), url: null, meta: {
      title: mk.name + " Job Guides — No Experience Needed | NoProbJobs",
      description: "No-experience job guides for " + mk.name + " by work type: pay, hiring steps, and free alerts for each." } });
  }
  // Static content pages (/about/, /partners/) — pages.html shell + pages.js, brand list inlined.
  // The same brand list rides the landing blob (see the landing __npj_data injection in bake()).
  const brands = await carouselBrands(list);
  cache.carouselBrands = brands;
  cache.staticByPath = {
    "/about/": { page: "about", brands },
    "/partners/": { page: "partners", brands },
  };
  routes.push({ type: "static", path: "/about/", url: null, meta: {
    title: "About NoProbJobs | No-Experience & Entry Level Jobs",
    description: "Why NoProbJobs exists and how it works. Every job is checked for experience requirements, so what is left are no-experience and entry level roles where none is needed or the employer will train you." } });
  routes.push({ type: "static", path: "/partners/", url: null, meta: {
    title: "Partner With NoProbJobs | A Free Job Seeker Resource",
    description: "Partner with NoProbJobs, a free tool for workforce centers, nonprofits, schools, libraries, and community programs helping people find no-experience and entry level jobs." } });

  const server = serve(cache);
  await new Promise((r) => server.listen(PORT, r));
  const base = "http://localhost:" + PORT;
  routes.forEach((r) => { r.url = base + r.path; });

  // ---- Incremental bake: decide which job pages can be reused from the last bake ----
  // Defined here (not inside the render try) so the manifest write + stale sweep after the
  // try/finally can still see them. Only job pages are hashed/skipped; browse + landing always render.
  const jobRoutes = routes.filter((r) => r.type === "job");
  const nonJob = routes.filter((r) => r.type !== "job");
  const jobByPath = {}; for (const r of jobRoutes) jobByPath[r.path] = r;
  const templateVer = await computeTemplateVersion();
  let prevManifest = { templateVersion: null, pages: {} };
  if (!BAKE_FULL && existsSync(MANIFEST_PATH)) { try { prevManifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf8")); } catch (e) { /* corrupt -> full rebake */ } }
  const templateMatch = !BAKE_FULL && prevManifest.templateVersion === templateVer;
  const isNewByNum = {}; for (const r of list) isNewByNum[String(r.job_number)] = !!r.is_new;
  const diskFile = (rp) => join(OUT, rp.replace(/\/$/, ""), "index.html");
  // Sitemap <lastmod> (batch 1 A): the date THIS page's content last changed, tracked in the
  // manifest — NEVER the employer's posted_at. `bakeStamp` = this pull's date. A manifest entry is
  // {h: content-hash, c: changed_at}. A page whose hash is unchanged keeps its prior changed_at; a
  // new or changed page takes bakeStamp (a brand-new job's changed_at is the first bake it appears
  // in — the first_seen-equivalent). Old string-hash entries (pre-batch-1) are read as {h, c:null}.
  const bakeStamp = (() => { const d = String((meta[0] && meta[0].pulled_at) || "").slice(0, 10); return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : new Date().toISOString().slice(0, 10); })();
  const prevEntry = (p) => { const e = prevManifest.pages[p]; return (e && typeof e === "object") ? e : (typeof e === "string" ? { h: e, c: null } : null); };
  for (const r of jobRoutes) {
    r._hash = sha1(JSON.stringify({ d: cache.byNum[String(r.num)] || null, n: isNewByNum[String(r.num)] || false, ld: r.ld || null, rel: r.related || null }));
    const pe = prevEntry(r.path);
    r._changedAt = (pe && pe.c && pe.h === r._hash) ? pe.c : bakeStamp;   // unchanged -> keep date; new/changed -> this pull
    // Skip only on a normal full run (never on ONLY/LIMIT partials); needs matching template,
    // matching content hash, AND the file actually present on disk.
    r._skip = fullRun && templateMatch && pe && pe.h === r._hash && existsSync(diskFile(r.path));
  }
  const toBake = jobRoutes.filter((r) => !r._skip);
  const reused = jobRoutes.length - toBake.length;
  if (fullRun) process.stderr.write("  incremental: " + reused + " job page(s) reused, " + toBake.length + " to bake"
    + (BAKE_FULL ? " (BAKE_FULL forced)" : templateMatch ? "" : " — template changed, full rebake") + "\n");
  // protocolTimeout raised well above the 180s default: under a 6-wide pool a page.evaluate can
  // queue behind others long enough to trip it, and the page set has grown (oracle_orc unblocked),
  // so 480s gives headroom. Any residual timeout is a heal-able flake — see the breaker below.
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"], protocolTimeout: 480000 });

  // Circuit breaker: a failing build should die fast and loud, not grind through hundreds
  // of identical errors. Abort the moment 5 failures land in a row, or once >=10% of
  // attempted routes have failed (the percentage rule waits for a 10-route sample so a
  // lone blip can't nuke a healthy run) — whichever trips first.
  const MAX_CONSEC = 5, PCT = 0.10, PCT_FLOOR = 10;
  // Transient render flakes — Chrome protocol timeouts / dropped targets under the concurrent pool —
  // are re-baked one-at-a-time by healFailures() and reliably clear. They must NOT trip the
  // consecutive-failure breaker (a 5-flake cluster once aborted a COMPLETE build before heal ran).
  // They still count toward the ≥10% PCT breaker, so a genuine flake STORM (e.g. dead Chrome)
  // still aborts fast. A real render/inject error (not a flake) trips the consecutive breaker as before.
  const isFlake = (e) => /timed out|protocoltimeout|Runtime\.callFunctionOn|Target closed|Session closed|socket hang up|ECONNRESET|Navigation timeout/i.test(e || "");
  const breaker = { attempted: 0, fails: 0, flakes: 0, consec: 0, done: 0, aborted: false, reason: null, firstError: null, smokeFailed: false };
  const results = [];
  async function runRoutes(list){
    let next = 0;
    const workers = Array.from({ length: CONC }, async () => {
      const page = await browser.newPage();
      await page.setViewport(MOBILE);
      await attachCache(page, cache);
      while (!breaker.aborted) {
        const i = next++; if (i >= list.length) break;
        const res = await bake(page, list[i], cache);
        results.push(res); breaker.attempted++; breaker.done++;
        if (res.error) {
          breaker.fails++;
          if (!breaker.firstError) {                       // surface the first failure the instant it lands
            breaker.firstError = { path: res.path, error: res.error };
            process.stderr.write("  !! FIRST FAILURE (route " + breaker.attempted + ") " + res.path + ": " + res.error + "\n");
          }
          if (isFlake(res.error)) {
            breaker.flakes++;                              // heal-able: does NOT advance the consecutive breaker
          } else if (++breaker.consec >= MAX_CONSEC) {
            breaker.aborted = true; breaker.reason = MAX_CONSEC + " consecutive failures";
          }
          // PCT breaker counts ALL failures (incl. flakes) so a genuine storm still aborts fast.
          if (!breaker.aborted && breaker.attempted >= PCT_FLOOR && breaker.fails >= breaker.attempted * PCT) {
            breaker.aborted = true; breaker.reason = "≥" + (PCT * 100) + "% of attempted routes failed";
          }
        } else breaker.consec = 0;
        if (breaker.done % 25 === 0 || breaker.done === routes.length) {
          const el = ((Date.now() - t0) / 1000).toFixed(0);
          process.stderr.write("  " + breaker.done + "/" + routes.length + "  ok " + (breaker.done - breaker.fails) + "  failed " + breaker.fails + "  " + el + "s\n");
        }
      }
      await page.close();
    });
    await Promise.all(workers);
  }

  // Self-heal: the only failures a healthy run produces are protocolTimeout flakes — a
  // page.evaluate that queued too long behind the 6-wide pool. Re-bake the failed routes
  // ONE at a time (no pool, no contention) and swap each success back into results. What
  // still fails after this is a real error, not a flake. Runs only on a non-aborted build.
  async function healFailures(){
    const failed = routes.filter((r) => results.some((x) => x.path === r.path && x.error));
    if (!failed.length) return;
    process.stderr.write("  ~~ healing " + failed.length + " failed route(s) sequentially\n");
    const page = await browser.newPage();
    await page.setViewport(MOBILE);
    await attachCache(page, cache);
    for (const route of failed){
      const res = await bake(page, route, cache);
      const idx = results.findIndex((x) => x.path === route.path && x.error);
      if (!res.error && idx !== -1) { results[idx] = res; breaker.fails--; process.stderr.write("  ~~ healed " + route.path + "\n"); }
      else if (res.error) process.stderr.write("  ~~ still failing " + route.path + ": " + res.error + "\n");
    }
    await page.close();
  }

  try {
    if (ONLY) {
      const set = new Set(ONLY.map(String));
      await runRoutes(jobRoutes.filter((r) => set.has(String(r.num))));   // targeted rebake; no smoke/breaker gymnastics
    } else if (LIMIT) {
      await runRoutes([...jobRoutes.slice(0, LIMIT), ...nonJob]);
    } else {
      // Smoke FIRST: 8 job pages + every browse/landing route. A broken render/inject path
      // surfaces here in seconds — before the full run, not as a post-mortem. Smoke draws from
      // toBake (the not-reused set); if everything's reused, smoke is just the nonJob routes.
      await runRoutes([...toBake.slice(0, SMOKE), ...nonJob]);
      breaker.smokeFailed = results.some((r) => r.error && !isFlake(r.error));   // a flake in smoke is heal-able, not a broken path
      if (!breaker.smokeFailed && !breaker.aborted) await runRoutes(toBake.slice(SMOKE));
    }
    if (!breaker.aborted && !breaker.smokeFailed) await healFailures();
  } finally {
    await browser.close();
    server.close();
  }

  // ---- Incremental-bake manifest + stale-page sweep (full runs only, on a clean bake) ----
  // Only persist/sweep when the run wasn't aborted and smoke passed — never record or prune off a
  // broken build. On a clean full run: (1) write the manifest = reused hashes + freshly-baked
  // hashes (failed pages omitted, so they re-render next time); (2) delete on-disk /jobs/{slug}/
  // dirs that aren't in the current PUBLISHED job set — this is how a suppressed employer / a
  // geo-leak / a removed job stops resolving at its direct URL WITHOUT a manual `rm -rf out`.
  let staleSwept = 0;
  if (fullRun && !breaker.aborted && !breaker.smokeFailed) {
    const newPages = {};
    for (const r of jobRoutes) if (r._skip) newPages[r.path] = { h: r._hash, c: r._changedAt };
    for (const res of results) if (res.type === "job" && !res.error && jobByPath[res.path]) { const jr = jobByPath[res.path]; newPages[res.path] = { h: jr._hash, c: jr._changedAt }; }
    await writeFile(MANIFEST_PATH, JSON.stringify({ templateVersion: templateVer, pages: newPages }), "utf8");

    const liveSet = new Set(jobRoutes.map((r) => r.path));
    const jobsDir = join(OUT, "jobs");
    if (existsSync(jobsDir)) {
      for (const ent of await readdir(jobsDir, { withFileTypes: true })) {
        if (!ent.isDirectory()) continue;
        if (!liveSet.has("/jobs/" + ent.name + "/")) { await rm(join(jobsDir, ent.name), { recursive: true, force: true }); staleSwept++; }
      }
    }
    if (staleSwept) process.stderr.write("  swept " + staleSwept + " stale job page(s) not in the published set\n");
  }

  // Lifecycle manifest — derived from the DB every run (independent of which pages were
  // baked), so a targeted rebake still leaves it complete. Drives the deploy's HTTP status
  // (expired -> 410) and the sitemap (live only). retired = a baked file that no longer has
  // a live/expired entry AND whose expiry aged out; the retire job (not this build) deletes it.
  const live = recs.filter((r) => !r.expired).map((r) => jobPath(r) + "/");
  const expired = recs.filter((r) => r.expired && !r.retired).map((r) => jobPath(r) + "/");   // 410 window (<30d)
  const retired = recs.filter((r) => r.retired).map((r) => jobPath(r) + "/");                 // retire.mjs deletes these
  const manifest = { generated: (meta[0] && meta[0].pulled_at) || null, live, expired, retired, browse: [...browsePaths] };
  await mkdir(OUT, { recursive: true });
  await writeFile(join(OUT, "_lifecycle.json"), JSON.stringify(manifest), "utf8");

  const expiredBack = {};
  for (const r of recs) if (r.expired && !r.retired) {
    // Carry the job's browse path + its category/city so the 410 page's "Get job alerts"
    // link can seed the (email-only) modal silently — the highest-intent signal on the site.
    expiredBack[jobPath(r) + "/"] = { back: backTo(r.state, r.category).href,
      cat: (r.category && r.category[0]) || null, city: r.city || null };
  }
  // Killed records (intentional takedowns) are EXCLUDED from jobs_detail, so recs above can't see
  // them and their pages would be swept -> 404. analyze/gone.py (service-role, RLS-bypassing)
  // writes out/gone.json with their path fields; merge each into the 410 map so a killed job 410s
  // with the same "gone" page an expired job gets. Missing/empty file = no-op (publishable-key
  // bake never sees killed rows itself). These paths are NOT in `live`/the sitemap (recs excludes
  // killed), and the stale-page sweep removes their static dir — the middleware 410s via EXPIRED
  // before it would ever check for a static file.
  const gonePath = join(HERE, "..", "out", "gone.json");
  if (existsSync(gonePath)) {
    let goneList = [];
    try { goneList = JSON.parse(readFileSync(gonePath, "utf8")); } catch { goneList = []; }
    let goneMerged = 0;
    for (const r of (Array.isArray(goneList) ? goneList : [])) {
      if (!r || r.job_number == null || !r.slug) continue;
      expiredBack[jobPath(r) + "/"] = { back: backTo(r.state, r.category).href,
        cat: (r.category && r.category[0]) || null, city: r.city || null };
      goneMerged++;
    }
    if (goneMerged) process.stderr.write("  gone: merged " + goneMerged + " killed URL(s) into the 410 map\n");
  }

  // <lastmod> per sitemap URL (batch 1 A/B): the date OUR page content last changed, NEVER the
  // employer's posted_at (which stays untouched for datePosted / card date / board sort / New badge).
  // Job pages take their manifest changed_at; listing/browse views take the most-recent changed_at
  // among the live jobs in that slice (sliceChanged() — reused by batch 3 city pages); static pages
  // take their source module's last git-commit date. Omitted only when no honest date exists.
  const genDate = bakeStamp;   // retained alias: the pull date, for any downstream reference
  const validDay = (d) => /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : "";
  const changedAtByPath = {}; for (const r of jobRoutes) if (validDay(r._changedAt)) changedAtByPath[r.path] = r._changedAt;
  const lastmod = {};
  for (const r of recs) if (!r.expired && !r.retired) {
    const c = changedAtByPath[jobPath(r) + "/"];
    if (validDay(c)) lastmod[jobPath(r) + "/"] = c;
  }
  // Listing-view slice changed_at = most-recent changed_at among the slice's live jobs.
  // sliceChanged() is the reusable helper batch 3 city pages call with their own member set.
  const sliceRecs = {};
  for (const r of recs) { if (r.expired || r.retired) continue;
    const ps = new Set([browsePath(r.state, null)]);
    for (const c of (r.category || [])) ps.add(browsePath(r.state, c));
    for (const p of ps) (sliceRecs[p] = sliceRecs[p] || []).push(r);
  }
  const sliceChanged = (rs) => { let m = ""; for (const r of (rs || [])) { const c = changedAtByPath[jobPath(r) + "/"]; if (validDay(c) && c > m) m = c; } return m; };
  for (const u of browsePaths) { const c = sliceChanged(sliceRecs[u]); if (validDay(c)) lastmod[u] = c; }
  // Static pages: content-change date = last git commit touching the source module that renders the
  // page (auto-maintaining + honest), falling back to this pull's date if git is unavailable.
  const gitDate = (file) => { try { return execSync('git log -1 --format=%cs -- "' + file + '"', { cwd: join(HERE, ".."), encoding: "utf8" }).trim(); } catch { return ""; } };
  const STATIC_SRC = { "/": "noprobjobs/landing.js", [WA_LANDER]: "noprobjobs/landing.js", "/about/": "noprobjobs/pages.js", "/partners/": "noprobjobs/pages.js" };
  for (const [u, f] of Object.entries(STATIC_SRC)) lastmod[u] = validDay(gitDate(f)) || bakeStamp;
  const alertSrcDate = validDay(gitDate("noprobjobs/alerts.js")) || bakeStamp;
  for (const u of ALERT_PATHS) lastmod[u] = alertSrcDate;

  const deploy = await assembleDeploy(live, expiredBack, [...browsePaths], lastmod);

  const secs = (Date.now() - t0) / 1000;
  const jobs = results.filter((r) => r.type === "job");
  const failures = results.filter((r) => r.error);
  const bytes = (arr) => arr.filter((r) => r.bytes).map((r) => r.bytes);
  const avg = (a) => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length) : 0;
  const stopped = breaker.aborted || breaker.smokeFailed;
  const summary = {
    aborted: stopped,
    abort_reason: breaker.smokeFailed ? "smoke test failed — full run not started" : breaker.reason,
    first_error: breaker.firstError,
    routes_planned: routes.length,
    attempted: breaker.attempted,
    job_pages_ok: jobs.filter((r) => !r.error).length,
    job_pages_reused: reused,                                    // skipped by the incremental manifest
    job_pages_swept: staleSwept,                                 // stale pages deleted (suppressed/removed)
    job_pages_with_jsonld: jobs.filter((r) => r.ld).length,
    expired_no_jsonld: expiredCount,
    jj_ld_dropped: jjLdDropped,
    manifest_live: live.length,
    manifest_expired: expired.length,
    manifest_retired: retired.length,
    // Coverage: rows fetched vs the DB's authoritative count. A truncated fetch (row cap) shows
    // here and fails the bake, instead of silently shipping a partial site. jobs_fetched should
    // equal manifest_live+manifest_expired+retired on a healthy run.
    jobs_fetched: recsFetched.length, jobs_total: jobsTotal, jobs_published: recs.length,
    list_fetched: listFetched.length, list_total: listTotal, list_published: list.length,
    launched_states: [...LAUNCHED_STATES], suppressed_employers: [...SUPPRESSED_EMPLOYERS], suppressed_count: recsFetched.length - recs.length,
    coverage_complete: (jobsTotal == null || recsFetched.length >= jobsTotal) && (listTotal == null || listFetched.length >= listTotal),
    sitemap_urls: deploy.sitemap_urls,
    browse_pages_ok: results.filter((r) => r.type === "browse" && !r.error).length,
    landing_ok: results.filter((r) => r.type === "landing" && !r.error).length,
    failures: failures.length,
    sample_failures: failures.slice(0, 5).map((f) => ({ path: f.path, error: f.error })),
    avg_job_bytes: avg(bytes(jobs)),
    avg_browse_bytes: avg(bytes(results.filter((r) => r.type === "browse"))),
    total_build_seconds: Math.round(secs * 10) / 10,
    pages_per_second: secs > 0 ? Math.round((breaker.attempted / secs) * 10) / 10 : 0,
    concurrency: CONC,
  };
  console.log(JSON.stringify(summary, null, 2));

  // Terminal summary line in the house format ($ echo / output / one summary line), so a
  // silent bake failure can no longer read like a success. On any abort/route failure this
  // exits non-zero, which run_pull.py surfaces as STATUS: BAKE FAILED and halts the publish
  // before deploy. (Write failures throw out of main() -> the catch below -> exit 1.)
  const listingViews = summary.browse_pages_ok + summary.landing_ok;
  const truncated = !summary.coverage_complete;
  // Always emit coverage (parsed into the run record / dashboard signal), even on failure.
  console.log("BAKE COVERAGE: jobs " + summary.jobs_fetched + "/" + (summary.jobs_total ?? "?")
    + " list " + summary.list_fetched + "/" + (summary.list_total ?? "?") + " complete=" + summary.coverage_complete);
  if (stopped || failures.length || truncated) {
    process.exitCode = 1;
    console.error("BAKE FAILED: " + summary.job_pages_ok + " job pages ok, "
      + failures.length + " route failure(s)"
      + (summary.abort_reason ? " — " + summary.abort_reason : "")
      + (truncated ? " — FETCH TRUNCATED: saw " + summary.jobs_fetched + " of " + summary.jobs_total
          + " jobs (" + summary.list_fetched + " of " + summary.list_total + " live) — PostgREST row cap? fetchAll must paginate" : ""));
  } else {
    // Keep "<N> job pages, <M> listing views" verbatim — run_pull.py parses it. The incremental
    // breakdown follows in parentheses.
    console.log("BAKE COMPLETE: " + (summary.job_pages_ok + summary.job_pages_reused) + " job pages, "
      + listingViews + " listing views"
      + " (" + summary.job_pages_ok + " baked, " + summary.job_pages_reused + " reused"
      + (summary.job_pages_swept ? ", " + summary.job_pages_swept + " swept" : "") + ")");
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
