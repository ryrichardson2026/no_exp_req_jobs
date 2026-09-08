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
import { readFile, writeFile, mkdir, stat, rm } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { jobPostingLd, jobPostingScript } from "../noprobjobs/data/jobPosting.js";
import { jobPath, browsePath, CAT_SLUG, STATE_SLUG } from "../noprobjobs/data/routes.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const OUT = join(HERE, "out");
const COUNTRY = JSON.parse(readFileSync(join(HERE, "..", "config", "source_country.json"), "utf8"));
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const REST = "https://eyatyzatcmjnmazmaghd.supabase.co/rest/v1";
const KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE";
const PORT = 8795;
const CONC = 6;                                     // concurrent Chrome pages
const MOBILE = { width: 412, height: 915, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const MIME = { ".html":"text/html",".js":"text/javascript",".mjs":"text/javascript",".css":"text/css",
  ".json":"application/json",".svg":"image/svg+xml",".png":"image/png",".ico":"image/x-icon",".woff2":"font/woff2",".map":"application/json" };

const WAIT = {
  job: "document.querySelectorAll('[data-desc-html]').length >= 2 && !!document.querySelector('h1')",
  browse: "document.querySelectorAll(\"[role='list'] > *\").length > 0",
  landing: "document.getElementById('root') && document.getElementById('root').children.length > 0",
};

function serve(){
  return createServer(async (req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    try {
      if (p !== "/" && existsSync(join(SITE, p)) && (await stat(join(SITE, p))).isFile()) {
        res.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" });
        return res.end(await readFile(join(SITE, p)));
      }
      res.writeHead(200, { "content-type": "text/html" });
      res.end(await readFile(join(SITE, p === "/" ? "index.html" : "board.html")));
    } catch (e) { res.writeHead(500); res.end(String(e)); }
  });
}

async function fetchAll(path){
  const r = await fetch(REST + path, { headers: { apikey: KEY, Authorization: "Bearer " + KEY } });
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.json();
}

async function writeBaked(routePath, html){
  const dir = join(OUT, routePath.replace(/\/$/, ""));
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "index.html"), html, "utf8");
}

async function bake(page, route){
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
      const html = await page.evaluate(() => "<!DOCTYPE html>\n" + document.documentElement.outerHTML);
      await writeBaked(route.path, html);
      return { path: route.path, type: route.type, bytes: Buffer.byteLength(html, "utf8"), ld: !!route.ld };
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
      return req.continue();
    });
  });
}

async function main(){
  const t0 = Date.now();
  const LIMIT = process.env.LIMIT ? +process.env.LIMIT : 0;                 // LIMIT=N: bake first N jobs
  const ONLY = process.env.ONLY ? process.env.ONLY.split(",").map((s) => s.trim()) : null;  // ONLY=n,m: bake just these job_numbers
  const SMOKE = 8;                                                          // jobs in the smoke pass
  const fullRun = !LIMIT && !ONLY;
  if (fullRun) await rm(OUT, { recursive: true, force: true });             // partial runs preserve existing out/
  const recs = await fetchAll("/jobs_detail?select=*&limit=2000");
  const list = await fetchAll("/jobs_list?select=*&limit=2000");
  const meta = await fetchAll("/site_meta?select=pulled_at");
  const cache = { list: JSON.stringify(list), meta: JSON.stringify(meta), byId: {}, byNum: {} };
  for (const r of recs) { cache.byId[r.internal_id] = r; cache.byNum[String(r.job_number)] = r; }

  // enumerate routes
  const routes = [];
  let ldCount = 0, expiredCount = 0;
  for (const r of recs) {
    const ld = r.expired ? null : jobPostingScript(jobPostingLd(r, COUNTRY));   // parity: none on expired
    if (r.expired) expiredCount++; if (ld) ldCount++;
    routes.push({ type: "job", path: jobPath(r) + "/", url: null, ld, num: r.job_number });
  }
  // browse: states present, and categories present within each state
  const byState = {};
  for (const r of recs) { if (!r.state) continue; (byState[r.state] = byState[r.state] || new Set()); (r.category || []).forEach((c) => byState[r.state].add(c)); }
  const browsePaths = new Set(["/jobs/"]);
  for (const st of Object.keys(byState)) {
    browsePaths.add(browsePath(st, null));
    for (const c of byState[st]) if (CAT_SLUG[c]) browsePaths.add(browsePath(st, c));
  }
  for (const p of browsePaths) routes.push({ type: "browse", path: p, url: null, ld: null });
  routes.push({ type: "landing", path: "/", url: null, ld: null });

  const server = serve();
  await new Promise((r) => server.listen(PORT, r));
  const base = "http://localhost:" + PORT;
  routes.forEach((r) => { r.url = base + r.path; });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"] });

  // Circuit breaker: a failing build should die fast and loud, not grind through hundreds
  // of identical errors. Abort the moment 5 failures land in a row, or once >=10% of
  // attempted routes have failed (the percentage rule waits for a 10-route sample so a
  // lone blip can't nuke a healthy run) — whichever trips first.
  const MAX_CONSEC = 5, PCT = 0.10, PCT_FLOOR = 10;
  const breaker = { attempted: 0, fails: 0, consec: 0, done: 0, aborted: false, reason: null, firstError: null, smokeFailed: false };
  const results = [];
  async function runRoutes(list){
    let next = 0;
    const workers = Array.from({ length: CONC }, async () => {
      const page = await browser.newPage();
      await page.setViewport(MOBILE);
      await attachCache(page, cache);
      while (!breaker.aborted) {
        const i = next++; if (i >= list.length) break;
        const res = await bake(page, list[i]);
        results.push(res); breaker.attempted++; breaker.done++;
        if (res.error) {
          breaker.fails++; breaker.consec++;
          if (!breaker.firstError) {                       // surface the first failure the instant it lands
            breaker.firstError = { path: res.path, error: res.error };
            process.stderr.write("  !! FIRST FAILURE (route " + breaker.attempted + ") " + res.path + ": " + res.error + "\n");
          }
          if (breaker.consec >= MAX_CONSEC) { breaker.aborted = true; breaker.reason = MAX_CONSEC + " consecutive failures"; }
          else if (breaker.attempted >= PCT_FLOOR && breaker.fails >= breaker.attempted * PCT) { breaker.aborted = true; breaker.reason = "≥" + (PCT * 100) + "% of attempted routes failed"; }
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
      breaker.smokeFailed = results.some((r) => r.error);
      if (!breaker.smokeFailed && !breaker.aborted) await runRoutes(jobRoutes.slice(SMOKE));
    }
  } finally {
    await browser.close();
    server.close();
  }

  // Lifecycle manifest — derived from the DB every run (independent of which pages were
  // baked), so a targeted rebake still leaves it complete. Drives the deploy's HTTP status
  // (expired -> 410) and the sitemap (live only). retired = a baked file that no longer has
  // a live/expired entry AND whose expiry aged out; the retire job (not this build) deletes it.
  const live = recs.filter((r) => !r.expired).map((r) => jobPath(r) + "/");
  const expired = recs.filter((r) => r.expired).map((r) => jobPath(r) + "/");
  const manifest = { generated: (meta[0] && meta[0].pulled_at) || null, live, expired, browse: [...browsePaths] };
  await mkdir(OUT, { recursive: true });
  await writeFile(join(OUT, "_lifecycle.json"), JSON.stringify(manifest), "utf8");

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
  if (stopped || failures.length) process.exitCode = 1;
}

main().catch((e) => { console.error(e); process.exit(1); });
