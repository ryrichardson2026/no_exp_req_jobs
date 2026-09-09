/* Per-page SEO metadata — title, meta description, canonical, Open Graph — built PER
   RECORD at bake time, injected into the baked <head> by prerender/build.mjs. Pure module
   (no window), so the build can import it in Node.

   Two rules govern the strings:
   - Every value is derived: pay/city/experience come from the record via the SAME helpers
     the card uses (money / cityName / EXP_LABEL), so the metadata and the visible page can
     never disagree. Absence omits the clause — pay is dropped when the employer stated none.
   - Browse-page COUNTS are NOT computed here; build.mjs reads the board's rendered
     "N jobs found" number off the page and passes it in, so the description count is
     literally the same number the page shows. */
import { stateName, MARKET } from "./routes.js";

const BRAND = "NoProbJobs";                      // titles use the bare brand; the domain shows above it in results
const DIFF = "No sign-up, no resume, free to apply.";
const PERIOD = { HOURLY: "/hr", ANNUAL: "/yr", WEEKLY: "/wk", MONTHLY: "/mo", DAILY: "/day" };
const EXP_LABEL = { NONE_NEEDED: "No experience required", PREFERRED: "Experience preferred, not required", WAIVED: "No experience required" };

// mirrors record.js money() — the exact pay string the card renders, or null when unstated
function money(r){
  if (!r.salary_is_stated) return null;
  const f = (x) => "$" + (x % 1 ? x.toFixed(2) : x.toLocaleString());
  const per = PERIOD[r.pay_period] || "";
  const lo = r.salary_min != null ? Number(r.salary_min) : null, hi = r.salary_max != null ? Number(r.salary_max) : null;
  if (lo && hi && lo !== hi) return f(lo) + "–" + f(hi) + per;
  const one = lo || hi; return one ? f(one) + per : null;
}
// mirrors resolve.js cityName() — title-case only an all-caps value, else leave as published
function cityDisplay(s){
  const raw = String(s || "").trim().replace(/\s+/g, " ");
  if (!raw || raw !== raw.toUpperCase()) return raw;
  const small = { of: 1, the: 1, and: 1, de: 1, la: 1 };
  return raw.toLowerCase().split(" ").map((w, i) => (i > 0 && small[w]) ? w
    : w.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("-")).join(" ");
}
function locClause(r){
  const city = cityDisplay(r.city), st = r.state;
  return city && st ? " in " + city + ", " + st : (st ? " in " + st : "");   // null-state -> no clause
}
const employerOf = (r) => String(r.company_name || "").split(" /")[0];

export function jobTitle(r){ return r.title + " at " + employerOf(r) + locClause(r) + " | " + BRAND; }
export function jobDescription(r){
  let d = r.title + " at " + employerOf(r) + locClause(r) + ".";
  const pay = money(r); if (pay) d += " " + pay + ".";
  const exp = EXP_LABEL[r.experience_condition]; if (exp) d += " " + exp + ".";
  return d;
}

export function landingTitle(){ return BRAND + " — Jobs Hiring Now, No Experience Needed"; }
export function landingDescription(){ return stateName(MARKET) + " jobs hiring now, no experience required. " + DIFF; }

/* The Washington lander (change #2): the landing page served at /washington-jobs, whose only
   content difference is the "Washington companies hiring now." headline. Its own title/
   description so it reads as a distinct indexable page; canonical points to itself (set by
   the baker from the route path). */
export function waLanderTitle(){ return "Washington Companies Hiring Now, No Experience Needed | " + BRAND; }
export function waLanderDescription(){ return "Washington companies hiring now, no experience required. " + DIFF; }

export function stateTitle(abbr){ return "Jobs in " + stateName(abbr) + " - No Experience Needed | " + BRAND; }
export function stateDescription(abbr, count){ return count + " " + stateName(abbr) + " jobs hiring now, no experience required. " + DIFF; }
export function stateH1(abbr){ return "Jobs in " + stateName(abbr); }

export function categoryTitle(cat, abbr){ return cat + " Jobs in " + stateName(abbr) + " - No Experience Needed | " + BRAND; }
export function categoryDescription(cat, abbr, count){ return count + " " + cat.toLowerCase() + " jobs in " + stateName(abbr) + " hiring now, no experience required. " + DIFF; }
export function categoryH1(cat, abbr){ return cat + " jobs in " + stateName(abbr); }

function esc(s){ return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

/* The <head> tags to inject (title is set separately via document.title). og:title /
   twitter:title == the page title; og:description / twitter:description == the meta
   description; og:url == canonical; one site-wide OG image; the favicon set. */
export function metaHead({ title, description, canonical, ogImage }){
  return [
    '<meta name="description" content="' + esc(description) + '">',
    '<link rel="canonical" href="' + esc(canonical) + '">',
    '<meta property="og:type" content="website">',
    '<meta property="og:site_name" content="' + BRAND + '">',
    '<meta property="og:title" content="' + esc(title) + '">',
    '<meta property="og:description" content="' + esc(description) + '">',
    '<meta property="og:url" content="' + esc(canonical) + '">',
    '<meta property="og:image" content="' + esc(ogImage) + '">',
    '<meta property="og:image:width" content="1200">',
    '<meta property="og:image:height" content="630">',
    '<meta name="twitter:card" content="summary_large_image">',
    '<meta name="twitter:title" content="' + esc(title) + '">',
    '<meta name="twitter:description" content="' + esc(description) + '">',
    '<meta name="twitter:image" content="' + esc(ogImage) + '">',
    '<link rel="icon" href="/favicon.ico" sizes="any">',
    '<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
  ].join("\n");
}
