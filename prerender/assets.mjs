/* Generate the brand assets from the NoProbJobs mark (noprobjobs_logo_optimized.png):
   favicon set + header logo + Open Graph share image, into noprobjobs/. The mark is a
   yellow badge (navy ring, white thumb). It is circle-clipped to the mark's measured
   bounding box (centred on the art, not the padded frame), so the navy rim reaches the
   clip edge with transparent corners — it sits cleanly on the navy header/tab. apple-touch
   stays opaque (Apple composites transparency on black and rounds the corners). The OG
   card puts the badge on the navy ground, where the yellow pops. Run: node assets.mjs */
import puppeteer from "puppeteer-core";
import { writeFile, readFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const SRC = join(HERE, "..", "noprobjobs_logo_optimized.png");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const INK = "#0A3A75", MARK = "#F5C518", RED = "#C0392B";

const uri = "data:image/png;base64," + (await readFile(SRC)).toString("base64");

const b = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"] });
const p = await b.newPage();

// Measure the mark's real content bounding box (non-white, non-transparent pixels) so the
// circle clip is centred on the ART, not on the source frame — the source pads the badge
// off-centre, which a fixed clip turns into a white crescent. From the bbox we know the
// badge centre + diameter, and every size clips to exactly that circle. (0.985 pulls the
// clip a hair inside the navy rim so edge anti-aliasing never leaks a white pixel.)
const geo = await p.evaluate(async (u) => {
  const img = new Image(); img.src = u; await img.decode();
  const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
  const g = c.getContext("2d"); g.drawImage(img, 0, 0);
  const { data, width, height } = g.getImageData(0, 0, img.width, img.height);
  let minx = width, miny = height, maxx = 0, maxy = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++){
    const i = (y * width + x) * 4;
    const near = data[i + 3] < 12 || (data[i] > 244 && data[i + 1] > 244 && data[i + 2] > 244);
    if (!near){ if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y; }
  }
  return { width, height, cx: (minx + maxx) / 2, cy: (miny + maxy) / 2, dia: Math.max(maxx - minx, maxy - miny) };
}, uri);

// circle-clip centred on the measured badge, transparent outside the circle
const circle = (px) => {
  const scale = px / (geo.dia * 0.985);
  const w = Math.round(geo.width * scale), h = Math.round(geo.height * scale);
  const left = Math.round(px / 2 - geo.cx * scale), top = Math.round(px / 2 - geo.cy * scale);
  return '<div style="width:' + px + 'px;height:' + px + 'px;border-radius:50%;overflow:hidden;position:relative">'
    + '<img src="' + uri + '" style="position:absolute;left:' + left + 'px;top:' + top + 'px;width:' + w + 'px;height:' + h + 'px">'
    + '</div>';
};

// opaque padded tile for apple-touch (transparency would composite on black on iOS)
const tile = (px) =>
  '<div style="width:' + px + 'px;height:' + px + 'px;background:#fff;display:grid;place-items:center">'
  + '<img src="' + uri + '" style="width:' + Math.round(px * 0.98) + 'px;height:' + Math.round(px * 0.98) + 'px;object-fit:contain">'
  + '</div>';

const ogHtml = '<div style="width:1200px;height:630px;box-sizing:border-box;background:' + INK + ';display:flex;align-items:center;gap:56px;padding:0 90px;font-family:Arial,Helvetica,sans-serif;color:#fff">'
  + '<div style="flex:none">' + circle(300) + '</div>'
  + '<div style="min-width:0">'
  + '<div style="font-size:36px;font-weight:800;color:' + MARK + ';letter-spacing:1px">NoProbJobs.com</div>'
  + '<div style="font-size:78px;font-weight:900;line-height:1.03;margin-top:16px;text-transform:uppercase">Get hired now.</div>'
  + '<div style="background:' + RED + ';color:#fff;font-size:30px;font-weight:800;padding:11px 22px;margin-top:26px;display:inline-block;text-transform:uppercase;letter-spacing:1px">No experience needed</div>'
  + '</div></div>';

async function shot(html, w, hgt, out, omit){
  await p.setViewport({ width: w, height: hgt, deviceScaleFactor: 1 });
  await p.setContent("<!doctype html><meta charset=utf-8><style>*{margin:0;padding:0}html,body{width:" + w + "px;height:" + hgt + "px}</style>" + html, { waitUntil: "domcontentloaded" });
  await p.evaluate(() => document.fonts && document.fonts.ready);
  await p.evaluate(() => new Promise((r) => setTimeout(r, 100)));
  const png = await p.screenshot({ clip: { x: 0, y: 0, width: w, height: hgt }, omitBackground: !!omit });
  if (out) await writeFile(out, png);
  return png;
}

await shot(circle(192), 192, 192, join(SITE, "icon-192.png"), true);
await shot(circle(128), 128, 128, join(SITE, "logo.png"), true);
await shot(tile(180), 180, 180, join(SITE, "apple-touch-icon.png"), false);
const ico = await shot(circle(32), 32, 32, null, true);
// wrap the 32x32 PNG in an ICO container (modern ICOs may embed PNG)
const head = Buffer.alloc(22);
head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(1, 4);        // reserved, type=icon, count=1
head.writeUInt8(32, 6); head.writeUInt8(32, 7); head.writeUInt8(0, 8); head.writeUInt8(0, 9);
head.writeUInt16LE(1, 10); head.writeUInt16LE(32, 12);                                // planes, bpp
head.writeUInt32LE(ico.length, 14); head.writeUInt32LE(22, 18);                       // size, offset
await writeFile(join(SITE, "favicon.ico"), Buffer.concat([head, ico]));

await shot(ogHtml, 1200, 630, join(SITE, "og.png"), false);

console.log("assets written from mark: favicon.ico, icon-192.png, apple-touch-icon.png, logo.png, og.png");
await b.close();
