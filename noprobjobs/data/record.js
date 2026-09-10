/* The record → card contract, extracted from Job Board.dc.html so the board and the
   landing page turn a record into card props through ONE implementation.
   Nothing is inferred here: pay renders only when salary_is_stated, posted only when
   posted_at parses, and every label is the employer's own value or a fixed string. */

import { LOGOS } from "./logos.js";

/* Fixed menu order — alphabetical-by-intent, never reordered by volume. Someone who
   learned where Warehouse sits finds it in the same place next visit. Every option
   stays in the menu and stays enabled, including the thin ones: a near-empty category
   is a sourcing gap that fills as employers are added, not a broken state.
   Category is a FILTER INPUT ONLY — it is never printed on a card or a job page. */
export const CATEGORIES = ["Administrative","Customer Service","Sales","Retail","Warehouse","Construction","Security","Facilities","Food Services"];
export function recordCats(r){ return Array.isArray(r.category) ? r.category : (r.category ? [r.category] : []); }

/* Presence filters. Facets group the employers' own raw values; the card and page
   still print shift_raw / employment_type verbatim, so nothing displayed is derived. */
export const SHIFT_FACETS = ["Day", "Swing", "Night", "Overnight", "Weekend", "Flexible"];
const SHIFT_MAP = { Day: /\b(day|morning|afternoon)\b/i, Swing: /\bevening\b/i, Night: /\bnight\b/i,
                    Overnight: /\bovernight\b/i, Weekend: /\bweekend\b/i, Flexible: /\b(variable|flexible)\b/i };
export function shiftFacets(raw){
  if (!raw) return [];
  return SHIFT_FACETS.filter((f) => SHIFT_MAP[f].test(raw));
}
export const TYPE_FACETS = ["Full-time", "Part-time"];
export function typeFacet(raw){
  if (!raw) return null;
  const v = String(raw).replace(/[\s_-]+/g, "").toLowerCase();
  if (v.indexOf("fulltime") === 0) return "Full-time";
  if (v.indexOf("parttime") === 0) return "Part-time";
  return null;                              // Per Diem, Seasonal, Temporary: neither facet
}

/* WAIVED and NONE_NEEDED carry the same promise to the applicant — nothing blocks
   applying — so they share one label. */
export const EXP_LABEL = { NONE_NEEDED:"No experience required", PREFERRED:"Experience preferred, not required", WAIVED:"No experience required" };
const PERIOD = { HOURLY:"/hr", ANNUAL:"/yr", WEEKLY:"/wk", MONTHLY:"/mo", DAILY:"/day" };
/* Set from data/jobs.js's PULLED_AT as soon as the records load. Until then it is
   the last known pull, so a label is never computed against the reader's clock —
   "Posted yesterday" would otherwise change meaning every day the file sits still. */
let TODAY = new Date(2026, 8, 3);
export function setToday(v){
  const t = parseDate(v);
  if (t !== null) TODAY = new Date(t);
  else console.warn("record.js: PULLED_AT missing or unparseable — posted labels fall back to the last known pull");
}
export function today(){ return TODAY; }

export function money(r){
  if (!r.salary_is_stated) return null;
  const f = (x) => "$" + (x % 1 ? x.toFixed(2) : x.toLocaleString());
  const per = PERIOD[r.pay_period] || "";
  const lo = r.salary_min, hi = r.salary_max;
  if (lo && hi && lo !== hi) return f(lo) + "–" + f(hi) + per;
  return f(lo || hi) + per;
}

export function parseDate(s){
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?/.exec(String(s || ""));
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0)).getTime();
}

/* Newest first, two-tier date key. Tier 1 — records with a real posted_at, newest to
   oldest. Tier 2 — records with none, below them, ordered by first_seen, which is an
   INTERNAL date never displayed in any form. internal_id breaks ties so the order is
   stable across re-renders. */
export function newestFirst(a, b){
  const pa = parseDate(a.posted_at), pb = parseDate(b.posted_at);
  if (pa && pb) return pb - pa || String(a.internal_id).localeCompare(String(b.internal_id));
  if (pa) return -1;
  if (pb) return 1;
  const fa = parseDate(a.first_seen) || 0, fb = parseDate(b.first_seen) || 0;
  return fb - fa || String(a.internal_id).localeCompare(String(b.internal_id));
}

/* Highest pay first. Every stated rate in this inventory is HOURLY, so rates compare
   directly — nothing is converted, and no figure is derived for a job that states none. */
export function payFirst(a, b){
  const pa = a.salary_is_stated, pb = b.salary_is_stated;
  if (pa && pb) {
    const va = a.salary_max || a.salary_min || 0, vb = b.salary_max || b.salary_min || 0;
    return vb - va || (b.salary_min || 0) - (a.salary_min || 0) || newestFirst(a, b);
  }
  if (pa) return -1;
  if (pb) return 1;
  return newestFirst(a, b);
}
export const SORTS = [{ id: "newest", label: "Newest first" }, { id: "pay", label: "Highest pay first" }];
export const COMPARATORS = { newest: newestFirst, pay: payFirst };

/* A stated posted date always renders. Old postings get coarser wording, never
   suppression. Only a genuinely absent posted_at produces no row. */
export function postedLabel(s){
  const t = parseDate(s);
  if (t === null) return null;              // no posted_at → no date row at all
  const n = Math.round((TODAY - t) / 86400000);
  if (n >= 365) return "Posted in " + new Date(t).getFullYear();
  if (n >= 60) return "Posted " + Math.round(n / 30) + " months ago";
  if (n >= 31) return "Posted last month";
  if (n < 0) return null;                   // a future date is not a freshness signal
  if (n === 0) return "Posted today";
  if (n === 1) return "Posted yesterday";
  return "Posted " + n + " days ago";
}

export function logoUrl(domain){
  return "https://www.google.com/s2/favicons?sz=128&domain=" + domain;
}
/* The employer name shown to people. Drops the parent-brand tail ("Providence / Providence
   Swedish / …" → "Providence") and any parenthetical ("U-Haul (U-Haul International / AMERCO)"
   → "U-Haul"). DISPLAY ONLY — the record's full company_name is untouched (dedupe, ownsDomain
   and brandSlug still read the real value). */
export function companyLabel(name){
  let s = String(name || "").split(" /")[0];
  const p = s.indexOf("(");
  if (p > 0) s = s.slice(0, p);
  return s.trim();
}
/* Brand slug from a company name, matching the logo FILE naming: drop the parent-brand
   tail ("Providence / …" → "Providence") and any parenthetical ("U-Haul (…)" → "U-Haul"),
   then lowercase and hyphenate. Fred Meyer/QFC (which share kroger.com and so fail
   ownsDomain) and every future brand resolve by NAME here, not by domain. */
export function brandSlug(companyName){
  let s = String(companyName || "").split(" /")[0];
  const p = s.indexOf("(");
  if (p > 0) s = s.slice(0, p);
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
/* A hand-picked local logo for this employer, or null. Keyed on the brand slug so it
   works where the domain favicon can't (kroger.com → Fred Meyer vs QFC). LOGOS is
   generated by the build from the files actually present in logos/, so a hit here means
   the file exists in the deploy — no runtime existence probe needed. Overrides logoUrl. */
export function localLogo(companyName){
  const f = LOGOS[brandSlug(companyName)];
  return f ? "/logos/" + f : null;
}
/* A logo is only this employer's if employer_domain belongs to the brand itself.
   Fred Meyer/QFC carry kroger.com and every Compass brand carries compass-usa.com —
   the parent's mark would label the job with the wrong company, so those get a monogram. */
export function ownsDomain(companyName, domain){
  const root = String(domain || "").split(".")[0].replace(/[^a-z0-9]/gi, "").toLowerCase();
  const name = String(companyName || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  return !!root && !!name && (name.indexOf(root) === 0 || root.indexOf(name) === 0);
}
/* Images are built here, never as src="{{ … }}" in a template: a hole in a src would
   be fetched literally before hydration. */
export function logoImg(src, size){
  const React = window.React;
  return React.createElement("img", { src: src, alt: "", width: size, height: size,
    style: { width: size + "px", height: size + "px", objectFit: "contain", borderRadius: size > 20 ? "4px" : "3px", flex: "none" } });
}

/* card.py truncates the title with an explicit ellipsis; three lines at card width
   is about 88 characters, so a cut title visibly reads as cut. */
export function cardTitle(t){
  const s = String(t || "").trim();
  if (s.length <= 88) return s;
  const cut = s.slice(0, 88);
  const sp = cut.lastIndexOf(" ");
  return (sp > 60 ? cut.slice(0, sp) : cut).replace(/[,;:·—-]+$/, "") + "…";
}

export function shiftLabel(s){
  const v = String(s).trim();
  return /^variable$/i.test(v) ? "Shift varies" : v + " shift";
}

export function verbatim(r){
  if (r.experience_condition !== "PREFERRED" && r.experience_condition !== "WAIVED") return null;
  const hit = (r.evidence_clauses || []).find((c) => c.label === r.experience_condition) || (r.evidence_clauses || [])[0];
  return hit ? hit.clause.replace(/\s+/g, " ").trim() : null;
}
