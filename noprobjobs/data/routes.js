/* The URL scheme (D1) as config, in one place.

   Job pages are FLAT and permanent: /jobs/{slug}-{job_number}, matched on the number —
   the slug is decoration and may change, the number always resolves, no redirect ever.
   (job_number is a write-once sequential DB identity, NOT internal_id, which is a pull
   key that must never surface in a public URL.) Nothing derived (category, state) sits
   in a job URL.

   Browse pages are hierarchical: /{state}/ and /{state}/{category}/ — they ARE the
   geography and category. The state segment is derived PER RECORD (rec.state), never
   from the inventory: a set-derived market is a hardcode in disguise that breaks the
   day a second state onboards.

   Path is canonical; multi-category / shift / pay / location / sort / page are query
   refinements and never generate an indexable route. */
import { CATEGORIES } from "./record.js";

/* Launch market: an EXPLICIT parameter, not an inventory scan. The landing has no
   per-record state context, so its browse links use this; a second market is added
   here (or via a picker) deliberately. This is the "market is a parameter" rule — one
   named value, not a derivation from whatever states happen to be in the data. */
export const MARKET = "WA";

export const STATE_SLUG = {
  AL:"alabama", AK:"alaska", AZ:"arizona", AR:"arkansas", CA:"california", CO:"colorado",
  CT:"connecticut", DE:"delaware", DC:"district-of-columbia", FL:"florida", GA:"georgia",
  HI:"hawaii", ID:"idaho", IL:"illinois", IN:"indiana", IA:"iowa", KS:"kansas",
  KY:"kentucky", LA:"louisiana", ME:"maine", MD:"maryland", MA:"massachusetts",
  MI:"michigan", MN:"minnesota", MS:"mississippi", MO:"missouri", MT:"montana",
  NE:"nebraska", NV:"nevada", NH:"new-hampshire", NJ:"new-jersey", NM:"new-mexico",
  NY:"new-york", NC:"north-carolina", ND:"north-dakota", OH:"ohio", OK:"oklahoma",
  OR:"oregon", PA:"pennsylvania", RI:"rhode-island", SC:"south-carolina",
  SD:"south-dakota", TN:"tennessee", TX:"texas", UT:"utah", VT:"vermont", VA:"virginia",
  WA:"washington", WV:"west-virginia", WI:"wisconsin", WY:"wyoming",
};
const SLUG_STATE = {};
for (const k in STATE_SLUG) SLUG_STATE[STATE_SLUG[k]] = k;

const catToSlug = (c) => String(c).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
export const CAT_SLUG = {};
const SLUG_CAT = {};
CATEGORIES.forEach((c) => { CAT_SLUG[c] = catToSlug(c); SLUG_CAT[catToSlug(c)] = c; });

/* The nine category slugs are RESERVED against future metro names — a metro may never
   be added with one of these slugs, and category ALWAYS wins on collision (see
   resolveLevel2). Stated now, before any metro model exists, so precedence is a
   decision and not an accident of implementation order. */
export const CATEGORY_SLUGS = new Set(CATEGORIES.map(catToSlug));

export function stateSlug(abbr){ return STATE_SLUG[abbr] || null; }

export function jobPath(rec){
  return "/jobs/" + (rec.slug || "job") + "-" + rec.job_number;
}
/* Read the job reference from a /jobs/{slug}-{ref} path: the LAST hyphen-delimited
   segment. A plain integer -> { jobNumber } (canonical). The legacy internal_id form
   (nxj_+12hex) -> { internalId }, a short-lived transition fallback so links generated
   in testing still resolve. Anything else (e.g. /jobs/foo-abc) -> null: a 404, never a
   lookup on garbage. */
export function jobRefFromPath(pathname){
  const parts = String(pathname || "").replace(/\/+$/, "").split("/");
  const last = parts[parts.length - 1] || "";
  const seg = last.slice(last.lastIndexOf("-") + 1);
  if (/^\d+$/.test(seg)) return { jobNumber: parseInt(seg, 10) };
  if (/^nxj_[0-9a-f]{12}$/.test(seg)) return { internalId: seg };
  return null;
}

/* Browse path from a state abbrev (pass rec.state — per record) and optional category.
   No/unknown state -> the state-less all-jobs index /jobs/, NEVER a guessed state. */
export function browsePath(stateAbbr, category){
  const st = stateSlug(stateAbbr);
  if (!st) return "/jobs/";
  return "/" + st + (category && CAT_SLUG[category] ? "/" + CAT_SLUG[category] + "/" : "/");
}

/* Explicit level-2 precedence: category first (the nine fixed slugs), then metro when a
   model exists, else 404. Category always wins on collision. */
export function resolveLevel2(segment){
  if (CATEGORY_SLUGS.has(segment)) return { kind: "category", category: SLUG_CAT[segment] };
  // if (METROS[segment]) return { kind: "metro", metro: segment };   // no metro model yet
  return { kind: "404" };
}

/* Parse a pathname into a route the SPA acts on. */
export function parsePath(pathname){
  const parts = String(pathname || "").split("/").filter(Boolean);
  if (!parts.length) return { kind: "home" };
  if (parts[0] === "jobs") {
    if (parts.length === 1) return { kind: "browse", state: null, category: null };  // /jobs index
    const ref = jobRefFromPath("/" + parts.join("/"));
    return ref ? Object.assign({ kind: "job" }, ref) : { kind: "404" };   // non-numeric junk -> 404
  }
  const state = SLUG_STATE[parts[0]] || null;
  if (!state) return { kind: "other" };                       // reserved/unknown top-level
  if (!parts[1]) return { kind: "browse", state, category: null };
  const lvl2 = resolveLevel2(parts[1]);
  if (lvl2.kind === "category") return { kind: "browse", state, category: lvl2.category };
  return { kind: "404" };                                     // metro (none yet) / bad segment
}
