/* Generate the brand assets — favicon set + Open Graph share image — into noprobjobs/,
   so they ship as static files and the metaHead links resolve. Run once (and re-run only
   if the mark/OG design changes): node assets.mjs */
import puppeteer from "puppeteer-core";
import { writeFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = join(HERE, "..", "noprobjobs");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const INK = "#0A3A75", MARK = "#F5C518", RED = "#C0392B", INKD = "#062a57";

const markSvg = (n) => '<svg xmlns="http://www.w3.org/2000/svg" width="' + n + '" height="' + n + '" viewBox="0 0 64 64">'
  + '<rect width="64" height="64" rx="13" fill="' + INK + '"/>'
  + '<text x="32" y="48" font-family="Arial Black, Arial, sans-serif" font-size="47" font-weight="900" fill="' + MARK + '" text-anchor="middle">N</text></svg>';

const star = (px) => '<svg width="' + px + '" height="' + px + '" viewBox="0 0 200 200"><polygon points="100,3 126.8,35.3 168.6,31.4 164.7,73.2 197,100 164.7,126.8 168.6,168.6 126.8,164.7 100,197 73.2,164.7 31.4,168.6 35.3,126.8 3,100 35.3,73.2 31.4,31.4 73.2,35.3" fill="' + MARK + '" stroke="' + INKD + '" stroke-width="5" stroke-linejoin="miter"/></svg>';

const ogHtml = '<div style="width:1200px;height:630px;box-sizing:border-box;background:' + INK + ';display:flex;flex-direction:column;justify-content:center;padding:82px;font-family:Arial,Helvetica,sans-serif;color:#fff;position:relative;overflow:hidden">'
  + '<div style="font-size:34px;font-weight:800;color:' + MARK + ';letter-spacing:1px">NoProbJobs.com</div>'
  + '<div style="font-size:82px;font-weight:900;line-height:1.02;margin-top:22px;max-width:780px;text-transform:uppercase">Jobs hiring now.</div>'
  + '<div style="background:' + RED + ';color:#fff;font-size:30px;font-weight:800;padding:11px 22px;margin-top:28px;align-self:flex-start;text-transform:uppercase;letter-spacing:1px">No experience needed</div>'
  + '<div style="position:absolute;right:72px;top:50%;transform:translateY(-50%)">' + star(300) + '</div></div>';

const b = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox"] });
const p = await b.newPage();

async function shot(html, w, hgt, out, omit){
  await p.setViewport({ width: w, height: hgt, deviceScaleFactor: 1 });
  await p.setContent("<!doctype html><meta charset=utf-8><style>*{margin:0;padding:0}body{width:" + w + "px;height:" + hgt + "px}</style>" + html, { waitUntil: "domcontentloaded" });
  await p.evaluate(() => document.fonts && document.fonts.ready);
  await p.evaluate(() => new Promise((r) => setTimeout(r, 80)));
  const png = await p.screenshot({ clip: { x: 0, y: 0, width: w, height: hgt }, omitBackground: !!omit });
  if (out) await writeFile(out, png);
  return png;
}

await shot(markSvg(192), 192, 192, join(SITE, "icon-192.png"), true);
await shot(markSvg(180), 180, 180, join(SITE, "apple-touch-icon.png"), true);
const ico32 = await shot(markSvg(32), 32, 32, null, true);
// wrap the 32x32 PNG in an ICO container (modern ICOs may embed PNG)
const head = Buffer.alloc(22);
head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(1, 4);       // reserved, type=icon, count=1
head.writeUInt8(32, 6); head.writeUInt8(32, 7); head.writeUInt8(0, 8); head.writeUInt8(0, 9);
head.writeUInt16LE(1, 10); head.writeUInt16LE(32, 12);                               // planes, bpp
head.writeUInt32LE(ico32.length, 14); head.writeUInt32LE(22, 18);                    // size, offset
await writeFile(join(SITE, "favicon.ico"), Buffer.concat([head, ico32]));

await shot(ogHtml, 1200, 630, join(SITE, "og.png"));

console.log("assets written: favicon.ico, icon-192.png, apple-touch-icon.png, og.png");
await b.close();
