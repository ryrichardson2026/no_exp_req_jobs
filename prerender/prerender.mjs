/* D2 prerender (proof scope: one job page + one browse page).

   Loads each route in headless system Chrome, waits for the SPA to render, injects
   JobPosting JSON-LD into <head> on JOB pages only, and serializes the rendered DOM to a
   static file — keeping the module <script> so the runtime re-mounts and interactivity
   survives. Reads Supabase through the PUBLISHABLE key (jobs_list / jobs_detail); the
   service key is never needed for a read.

   Baked at a MOBILE viewport: Google indexes mobile-first, so the crawler renders the
   phone layout. The standalone job page is viewport-independent, so its DOM is the same
   either way; a browse page bakes as its list of cards.

   Run: npm run prerender   (from prerender/) */
import { createServer } from "node:http";
import { readFile, writeFile, mkdir, stat } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";
import { jobPostingLd, jobPostingScript } from "../noprobjobs/data/jobPosting.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");         // static SPA root
const OUT = join(HERE, "out");                       // baked output (also served as an overlay)
const COUNTRY = JSON.parse(readFileSync(join(HERE, "..", "config", "source_country.json"), "utf8"));
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const REST = "https://eyatyzatcmjnmazmaghd.supabase.co/rest/v1";
const KEY = "sb_publishable_T49bDaIS8d7-AhQ8SsFU0g_ZA55yNQE";
const PORT = 8791;
const MOBILE = { width: 412, height: 915, deviceScaleFactor: 2, isMobile: true, hasTouch: true };

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
  ".ico": "image/x-icon", ".woff2": "font/woff2", ".map": "application/json" };

// ── static + rewrite server (mirrors vercel.json) ──────────────────────────
// A file that exists is served. "/" -> index.html. Anything else -> board.html (the SPA
// routes it). An out/ overlay (a baked page) wins over the SPA fallback, so the parity
// pass re-mounts over the actual baked document.
function serve(){
  return createServer(async (req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    try {
      if (p !== "/" && existsSync(join(SITE, p)) && (await stat(join(SITE, p))).isFile()) {
        const buf = await readFile(join(SITE, p));
        res.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" });
        return res.end(buf);
      }
      const overlay = join(OUT, p.replace(/\/$/, ""), "index.html");
      if (existsSync(overlay)) { res.writeHead(200, { "content-type": "text/html" }); return res.end(await readFile(overlay)); }
      const entry = p === "/" ? "index.html" : "board.html";
      res.writeHead(200, { "content-type": "text/html" });
      res.end(await readFile(join(SITE, entry)));
    } catch (e) { res.writeHead(500); res.end(String(e)); }
  });
}

async function fetchJson(path){
  const r = await fetch(REST + path, { headers: { apikey: KEY, Authorization: "Bearer " + KEY } });
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.json();
}

async function writeBaked(routePath, html){
  const dir = join(OUT, routePath.replace(/\/$/, ""));
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "index.html"), html, "utf8");
  return join(dir, "index.html");
}

const SERIALIZE = "'<!DOCTYPE html>\\n' + document.documentElement.outerHTML";

async function render(page, url, waitFn){
  await page.goto(url, { waitUntil: "networkidle0", timeout: 30000 });
  await page.waitForFunction(waitFn, { timeout: 20000 });
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
}

async function main(){
  const server = serve();
  await new Promise((r) => server.listen(PORT, r));
  const base = "http://localhost:" + PORT;
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"] });
  const report = {};

  try {
    // ── JOB PAGE ────────────────────────────────────────────────────────
    const jobNumber = 2;
    const rec = (await fetchJson("/jobs_detail?select=*&job_number=eq." + jobNumber))[0];
    const routePath = "/jobs/" + rec.slug + "-" + rec.job_number + "/";
    const ld = jobPostingLd(rec, COUNTRY);
    const ldScript = jobPostingScript(ld);

    const jp = await browser.newPage();
    await jp.setViewport(MOBILE);
    const DESC_READY = "document.querySelectorAll('[data-desc-html]').length >= 2 && !!document.querySelector('h1')";
    await render(jp, base + routePath, DESC_READY);

    // inject JSON-LD into <head> — job pages ONLY (never a browse/landing page)
    await jp.evaluate((html) => {
      const t = document.createElement("template"); t.innerHTML = html.trim();
      document.head.appendChild(t.content.firstChild);
    }, ldScript);

    const bakedRootJob = await jp.evaluate(() => document.getElementById("root").innerHTML);
    const usedPulledAt = await jp.evaluate(() => window.__PULLED_AT_SEEN || null);
    const jobHtml = await jp.evaluate(() => "<!DOCTYPE html>\n" + document.documentElement.outerHTML);
    const jobFile = await writeBaked(routePath, jobHtml);

    // description visual + assertions
    await jp.screenshot({ path: join(OUT, "job-page.png"), fullPage: true });
    const desc = await jp.evaluate(() => {
      const box = document.querySelector("[data-desc-html]");
      return { pCount: box.querySelectorAll("p").length, liCount: box.querySelectorAll("li").length,
        ulCount: box.querySelectorAll("ul,ol").length, hasLiteralTags: /&lt;(p|li|ul)&gt;/i.test(box.innerHTML),
        textLen: box.textContent.trim().length };
    });
    report.job = { routePath, file: jobFile, bytes: Buffer.byteLength(jobHtml, "utf8"),
      h1: await jp.evaluate(() => document.querySelector("h1").textContent),
      hasListInDom: await jp.evaluate(() => !!document.querySelector("[role='list']")),  // standalone => false
      ldInHead: /application\/ld\+json/.test(jobHtml), desc, usedPulledAt,
      backLink: await jp.evaluate(() => { const a = document.querySelector("main a[href]"); return a ? { href: a.getAttribute("href"), text: a.textContent.trim() } : null; }) };
    await jp.close();

    // ── BROWSE PAGE ─────────────────────────────────────────────────────
    const bp = await browser.newPage();
    await bp.setViewport(MOBILE);
    const CARDS_READY = "(document.querySelectorAll(\"[role='list'] > *\").length > 0)";
    await render(bp, base + "/washington/", CARDS_READY);
    const browseHtml = await bp.evaluate(() => "<!DOCTYPE html>\n" + document.documentElement.outerHTML);
    const browseFile = await writeBaked("/washington/", browseHtml);
    report.browse = { routePath: "/washington/", file: browseFile, bytes: Buffer.byteLength(browseHtml, "utf8"),
      cardCount: await bp.evaluate(() => document.querySelectorAll("[role='list'] > *").length),
      ldInHead: /application\/ld\+json/.test(browseHtml) };
    await bp.close();

    // ── PARITY: re-mount over the baked job document, compare #root ──────
    const par = await browser.newPage();
    await par.setViewport(MOBILE);
    await render(par, base + routePath, DESC_READY);   // now served from out/ (the baked file)
    const remountedRootJob = await par.evaluate(() => document.getElementById("root").innerHTML);
    report.parity = { match: bakedRootJob === remountedRootJob,
      bakedLen: bakedRootJob.length, remountLen: remountedRootJob.length,
      scrollTop: await par.evaluate(() => window.scrollY) };
    if (!report.parity.match) {
      // first divergent index, for a quick diff
      let i = 0; while (i < bakedRootJob.length && bakedRootJob[i] === remountedRootJob[i]) i++;
      report.parity.firstDiffAt = i;
      report.parity.bakedAround = bakedRootJob.slice(Math.max(0, i - 60), i + 60);
      report.parity.remountAround = remountedRootJob.slice(Math.max(0, i - 60), i + 60);
    }
    await par.close();
  } finally {
    await browser.close();
    server.close();
  }

  console.log(JSON.stringify(report, null, 2));
}

main().catch((e) => { console.error(e); process.exit(1); });
