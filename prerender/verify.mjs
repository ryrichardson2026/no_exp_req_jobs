import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { backTo } from "../noprobjobs/data/routes.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 8792;
const MIME = { ".html":"text/html",".js":"text/javascript",".css":"text/css",".json":"application/json",".svg":"image/svg+xml",".png":"image/png",".ico":"image/x-icon",".woff2":"font/woff2",".map":"application/json" };

// ── back-link text across the three record shapes ──────────────────────────
const cases = [
  ["one category  (Facilities, WA)", "WA", ["Facilities"]],
  ["multi category (Retail+Food, WA)", "WA", ["Retail", "Food Services"]],
  ["uncategorised  ([], WA)", "WA", []],
  ["no state       (Administrative, null)", null, ["Administrative"]],
];
console.log("=== back-link (a href -> destination text) ===");
for (const [label, st, cats] of cases) { const b = backTo(st, cats); console.log(label.padEnd(38), "->", b.href.padEnd(24), JSON.stringify(b.label)); }

// ── desktop: opening a card from the board still opens the PANEL ────────────
const server = createServer(async (req, res) => {
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
await new Promise((r) => server.listen(PORT, r));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"] });
try {
  const pg = await browser.newPage();
  await pg.setViewport({ width: 1280, height: 900 });
  await pg.goto("http://localhost:" + PORT + "/washington/", { waitUntil: "networkidle0" });
  await pg.waitForFunction("document.querySelectorAll(\"[role='list'] > *\").length > 0", { timeout: 20000 });
  const before = await pg.evaluate(() => ({ url: location.pathname, hasList: !!document.querySelector("[role='list']"), listScroll: (document.querySelector("[data-list-scroller]")||{}).scrollTop }));
  // click the first card
  await pg.click("[role='list'] > *:first-child [role='button'], [role='list'] > *:first-child a, [role='list'] > *:first-child");
  await pg.evaluate(() => new Promise((r) => setTimeout(r, 400)));
  const after = await pg.evaluate(() => ({
    url: location.pathname,
    hasList: !!document.querySelector("[role='list']"),         // list still present => still the board
    panelH1: (document.querySelector("[role='list']") ? (document.querySelectorAll("h1")[0] || {}).textContent : null),
    h1count: document.querySelectorAll("h1").length,
    isJobUrl: /^\/jobs\//.test(location.pathname),
  }));
  console.log("\n=== desktop panel open-from-board ===");
  console.log("before:", JSON.stringify(before));
  console.log("after :", JSON.stringify(after));
  console.log("verdict: list still present after click =", after.hasList, "| url is a job url =", after.isJobUrl,
    "| panel shows a title =", !!after.panelH1);
  await pg.close();
} finally { await browser.close(); server.close(); }
