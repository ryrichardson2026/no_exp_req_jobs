/* Local deploy emulation — serves the baked out/ the way the deploy must, so the job
   lifecycle (200 live / 410 expired / 404 retired-or-unknown) can be proven before it
   ships. This is the behaviour spec the Vercel config has to reproduce.

   Precedence per request:
     1. a real asset file (styles.css, board.js, data/*, ui/*, vendor/*) -> 200
     2. a job path in the lifecycle manifest's `expired` list -> 410 + its baked body
     3. a baked page on disk (out/<path>/index.html, or out/index.html for "/") -> 200
     4. a job-shaped path with no baked file -> 404 + the named 404 page (retired/unknown)
     5. any other unbaked path -> SPA fallback (board.html), 200

   Run: node preview.mjs     (serves http://localhost:8799) */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const OUT = join(HERE, "out");
const PORT = 8799;
const MIME = { ".html":"text/html",".js":"text/javascript",".mjs":"text/javascript",".css":"text/css",
  ".json":"application/json",".svg":"image/svg+xml",".png":"image/png",".ico":"image/x-icon",".woff2":"font/woff2",".map":"application/json" };

const manifest = existsSync(join(OUT, "_lifecycle.json"))
  ? JSON.parse(readFileSync(join(OUT, "_lifecycle.json"), "utf8")) : { live: [], expired: [], browse: [] };
const EXPIRED = new Set(manifest.expired || []);

const norm = (p) => (p.endsWith("/") ? p : p + "/");        // trailingSlash canonical
const bakedFile = (p) => join(OUT, p.replace(/\/$/, ""), "index.html");
const isJobPath = (p) => /^\/jobs\/.+-\d+\/$/.test(p);

createServer(async (req, res) => {
  const p = decodeURIComponent(req.url.split("?")[0]);
  const send = (status, body, type) => { res.writeHead(status, { "content-type": type || "text/html" }); res.end(body); };
  try {
    // 1. real asset file
    if (p !== "/" && existsSync(join(SITE, p)) && (await stat(join(SITE, p))).isFile())
      return send(200, await readFile(join(SITE, p)), MIME[extname(p)] || "application/octet-stream");

    const path = p === "/" ? "/" : norm(p);
    const baked = p === "/" ? join(OUT, "index.html") : bakedFile(path);

    // 2. expired -> 410 with the baked body (route resolves, Google is told to drop it)
    if (EXPIRED.has(path) && existsSync(baked)) return send(410, await readFile(baked));
    // 3. baked live page -> 200
    if (existsSync(baked)) return send(200, await readFile(baked));
    // 4. a job URL with no baked file -> retired/unknown -> named 404
    if (isJobPath(path)) return send(404, await readFile(join(SITE, "404.html")));
    // 5. any other unbaked path -> SPA fallback
    return send(200, await readFile(join(SITE, "board.html")));
  } catch (e) { send(500, String(e)); }
}).listen(PORT, () => console.log("preview on http://localhost:" + PORT + "  (" + EXPIRED.size + " expired, " + (manifest.live || []).length + " live)"));
