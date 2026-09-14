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
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { jobPostingLd, jobPostingScript } from "../noprobjobs/data/jobPosting.js";
import { jobPath, browsePath, CAT_SLUG, STATE_SLUG, backTo } from "../noprobjobs/data/routes.js";
import * as PM from "../noprobjobs/data/pageMeta.js";
import * as R from "../noprobjobs/data/record.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const OUT = join(HERE, "out");
const COUNTRY = JSON.parse(readFileSync(join(HERE, "..", "config", "source_country.json"), "utf8"));
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const REST = "https://eyatyzatcmjnmazmaghd.supabase.co/rest/v1";
const KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE";
const PORT = 8795;
const CONC = 6;                                     // concurrent Chrome pages
const SITE_URL = (process.env.SITE_URL || "https://noprobjobs.com").replace(/\/$/, "");   // canonical + OG + sitemap base
const MOBILE = { width: 412, height: 915, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
// Change #2: the Washington lander — a landing-page clone (served from index.html, so it runs
// landing.js) that differs only in its headline. Baked as its own route; excluded from the
// state-browse machinery entirely (no filtering, no state param). Trailing slash to match how
// every other baked route is written and how trailingSlash serves it.
const WA_LANDER = "/washington-jobs/";
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
};

function serve(cache){
  return createServer(async (req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    try {
      if (p !== "/" && existsSync(join(SITE, p)) && (await stat(join(SITE, p))).isFile()) {
        res.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" });
        return res.end(await readFile(join(SITE, p)));
      }
      // "/" and the Washington lander are the landing SPA (index.html → landing.js); every
      // other virtual path is the board SPA (board.html → board.js).
      const isLanding = p === "/" || p.replace(/\/+$/, "") === WA_LANDER.replace(/\/+$/, "");
      let html = await readFile(join(SITE, isLanding ? "index.html" : "board.html"), "utf8");
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
    const r = await fetch(REST + base + sep + "offset=" + from + "&limit=" + PAGE, { headers: { apikey: KEY, Authorization: "Bearer " + KEY } });
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
  const r = await fetch(REST + view + "?select=job_number&limit=1", { headers: { apikey: KEY, Authorization: "Bearer " + KEY, Prefer: "count=exact" } });
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
async function assembleDeploy(live, expiredBack, browse){
  for (const f of ["board.html", "board.js", "landing.js", "styles.css", "404.html",
                   "favicon.ico", "icon-192.png", "apple-touch-icon.png", "og.png", "logo.png"]) await copyFile(join(SITE, f), join(OUT, f));
  for (const d of ["data", "ui", "vendor"]) await cp(join(SITE, d), join(OUT, d), { recursive: true });
  // Hand-picked brand logos live at repo-root logos/ (the user's drop folder), served from
  // /logos/ in the deploy. Same-origin, so no CSP host to allow. Cosmetic progressive
  // enhancement — skipped during bake (like favicons), copied here for the live site.
  if (existsSync(join(HERE, "..", "logos"))) await cp(join(HERE, "..", "logos"), join(OUT, "logos"), { recursive: true });

  const base = SITE_URL;
  const locs = ["/", WA_LANDER, ...browse, ...live];               // change #2: lander in sitemap; expired/retired excluded
  const xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + locs.map((u) => "  <url><loc>" + base + u + "</loc></url>").join("\n") + "\n</urlset>\n";
  await writeFile(join(OUT, "sitemap.xml"), xml, "utf8");

  // robots.txt — allow all + declare the sitemap. Written as a real file so Vercel serves it as
  // text/plain (its default for .txt), NOT routed through the SPA. Was missing (404) before.
  await writeFile(join(OUT, "robots.txt"),
    "User-agent: *\nAllow: /\nSitemap: " + base + "/sitemap.xml\n", "utf8");

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
      if (route.type === "landing" && cache) {
        const blob = JSON.stringify({ list: JSON.parse(cache.list), pulledAt: cache.pulledAt || null }).replace(/</g, "\\u003c");
        out = out.replace("</body>", '<script id="__npj_data" type="application/json">' + blob + "</script></body>");
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

async function main(){
  const t0 = Date.now();
  KEEP_SRCS = sourceScriptSrcs();
  process.stderr.write("  bake keeps source scripts: [" + KEEP_SRCS.join(", ") + "]\n");
  const logoSlugs = await generateLogoIndex();
  process.stderr.write("  logo index: " + logoSlugs.length + " brand logo(s) [" + logoSlugs.join(", ") + "]\n");
  const LIMIT = process.env.LIMIT ? +process.env.LIMIT : 0;                 // LIMIT=N: bake first N jobs
  const ONLY = process.env.ONLY ? process.env.ONLY.split(",").map((s) => s.trim()) : null;  // ONLY=n,m: bake just these job_numbers
  const SMOKE = 8;                                                          // jobs in the smoke pass
  const fullRun = !LIMIT && !ONLY;
  // The bake is INCREMENTAL — no rm(OUT). A job that crosses 30 days stops being baked
  // (skipped below), and its stale expired page stays on disk until retire.mjs deletes it;
  // that is the retire step's real work. Paths are stable (slug + job_number are write-once),
  // so live/expired pages just overwrite and nothing orphans.
  const recs = await fetchAll("/jobs_detail?select=*&order=job_number.asc");   // &order= = stable offset paging
  const list = await fetchAll("/jobs_list?select=*&order=job_number.asc");
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

  // enumerate routes
  const routes = [];
  let ldCount = 0, expiredCount = 0, retiredCount = 0;
  for (const r of recs) {
    if (r.retired) { retiredCount++; continue; }                              // retired -> not baked; retire.mjs removes any stale file
    const ld = r.expired ? null : jobPostingScript(jobPostingLd(r, COUNTRY)); // parity: no JSON-LD once expired
    if (r.expired) expiredCount++; if (ld) ldCount++;
    routes.push({ type: "job", path: jobPath(r) + "/", url: null, ld, num: r.job_number,
      meta: { title: PM.jobTitle(r), description: PM.jobDescription(r) } });
  }
  // browse: states present, and categories present within each state. state/category ride
  // on the route so bake() can build the title; the count comes from the rendered page.
  const byState = {};
  for (const r of recs) { if (!r.state) continue; (byState[r.state] = byState[r.state] || new Set()); (r.category || []).forEach((c) => byState[r.state].add(c)); }
  const browsePaths = new Set(["/jobs/"]);
  routes.push({ type: "browse", path: "/jobs/", url: null, state: null, category: null });
  for (const st of Object.keys(byState)) {
    const sp = browsePath(st, null); browsePaths.add(sp);
    routes.push({ type: "browse", path: sp, url: null, state: st, category: null });
    for (const c of byState[st]) if (CAT_SLUG[c]) { const cp = browsePath(st, c); browsePaths.add(cp); routes.push({ type: "browse", path: cp, url: null, state: st, category: c }); }
  }
  routes.push({ type: "landing", path: "/", url: null, meta: { title: PM.landingTitle(), description: PM.landingDescription() } });
  // Change #2: Washington lander. Same landing type (same render wait + meta injection), its
  // own path so bake() writes out/washington-jobs/index.html and sets canonical to itself.
  routes.push({ type: "landing", path: WA_LANDER, url: null, meta: { title: PM.waLanderTitle(), description: PM.waLanderDescription() } });

  const server = serve(cache);
  await new Promise((r) => server.listen(PORT, r));
  const base = "http://localhost:" + PORT;
  routes.forEach((r) => { r.url = base + r.path; });
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
    const jobRoutes = routes.filter((r) => r.type === "job");
    const nonJob = routes.filter((r) => r.type !== "job");
    if (ONLY) {
      const set = new Set(ONLY.map(String));
      await runRoutes(jobRoutes.filter((r) => set.has(String(r.num))));   // targeted rebake; no smoke/breaker gymnastics
    } else if (LIMIT) {
      await runRoutes([...jobRoutes.slice(0, LIMIT), ...nonJob]);
    } else {
      // Smoke FIRST: 8 job pages + every browse/landing route. A broken render/inject path
      // surfaces here in seconds — before the 895-page run, not as a 1.7-hour post-mortem.
      await runRoutes([...jobRoutes.slice(0, SMOKE), ...nonJob]);
      breaker.smokeFailed = results.some((r) => r.error && !isFlake(r.error));   // a flake in smoke is heal-able, not a broken path
      if (!breaker.smokeFailed && !breaker.aborted) await runRoutes(jobRoutes.slice(SMOKE));
    }
    if (!breaker.aborted && !breaker.smokeFailed) await healFailures();
  } finally {
    await browser.close();
    server.close();
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
  const deploy = await assembleDeploy(live, expiredBack, [...browsePaths]);

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
    job_pages_with_jsonld: jobs.filter((r) => r.ld).length,
    expired_no_jsonld: expiredCount,
    manifest_live: live.length,
    manifest_expired: expired.length,
    manifest_retired: retired.length,
    // Coverage: rows fetched vs the DB's authoritative count. A truncated fetch (row cap) shows
    // here and fails the bake, instead of silently shipping a partial site. jobs_fetched should
    // equal manifest_live+manifest_expired+retired on a healthy run.
    jobs_fetched: recs.length, jobs_total: jobsTotal,
    list_fetched: list.length, list_total: listTotal,
    coverage_complete: (jobsTotal == null || recs.length >= jobsTotal) && (listTotal == null || list.length >= listTotal),
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
    console.log("BAKE COMPLETE: " + summary.job_pages_ok + " job pages, "
      + listingViews + " listing views");
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
