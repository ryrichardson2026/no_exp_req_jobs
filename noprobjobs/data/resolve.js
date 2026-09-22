/* location/resolve.py's contract, client-side. Extracted from Job Board.dc.html so
   the board and the landing page resolve a location through ONE implementation.
   A five-digit entry is a ZIP and resolves through ZCTA centroids; anything else
   matches a city name exactly or by prefix (type-ahead). A ZIP with no centroid
   table loaded is unmatched — never guessed to the nearest city. No per-job
   distance is ever produced. */

export const RADII = [5, 10, 15];           // closed set, default 10 (tightened: 10mi in a metro ≈ a whole city)

/* Employers publish city names in different cases (Dollar General ships ABERDEEN,
   BENTON CITY…). Matching goes through one key so a filter can't hide a job whose
   spelling differs, and display goes through cityName() — formatting only, like
   money()/postedLabel(); the state is printed exactly as published. */
export function cityKey(s){ return String(s || "").trim().replace(/\s+/g, " ").toLowerCase(); }

const SMALL_WORDS = { of: 1, the: 1, and: 1, de: 1, la: 1 };
export function cityName(s){
  const raw = String(s || "").trim().replace(/\s+/g, " ");
  if (!raw || raw !== raw.toUpperCase()) return raw;      // already mixed case: leave it
  return raw.toLowerCase().split(" ").map((w, i) => {
    if (i > 0 && SMALL_WORDS[w]) return w;
    return w.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("-");
  }).join(" ");
}

export function haversine(a, b){
  const R = 3958.7613, rad = Math.PI / 180;
  const p1 = a[0] * rad, p2 = b[0] * rad;
  const dp = (b[0] - a[0]) * rad, dl = (b[1] - a[1]) * rad;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function resolveLocation(query, cities, zips){
  const q = String(query || "").trim();
  if (!q) return { kind: "all", cities: [] };
  if (/^\d{5}$/.test(q)) {
    const centroid = zips && zips[q];
    if (!centroid) return { kind: "unmatched-zip", zip: q, cities: [] };
    return { kind: "zip", zip: q, centroid, cities: [] };
  }
  const ql = cityKey(q);
  const states = {};
  cities.forEach((c) => { if (c.state) states[c.state.toLowerCase()] = c.state; });
  if (states[ql]) return { kind: "state", state: states[ql], cities: [] };
  const exact = [], prefix = [];
  cities.forEach((c) => {
    const n = cityKey(c.city);
    if (n === ql) exact.push(c); else if (n.indexOf(ql) === 0) prefix.push(c);
  });
  const hits = exact.concat(prefix.sort((a, b) => a.city.localeCompare(b.city)));
  if (!hits.length) return { kind: "unmatched", query: q, cities: [] };
  // cities = match keys; display = the index's own spelling, never a re-cased key
  return { kind: "city", query: q, cities: hits.map((c) => cityKey(c.city)), display: hits.map((c) => c.city) };
}

/* The unrecognised-entry copy lives with the resolver, so both screens say the
   same thing about the same input. */
export function unmatchedLine(res, raw){
  if (res.kind === "unmatched-zip") return "ZIP " + res.zip + " isn’t recognised.";
  return "“" + raw + "” isn’t a city, state or ZIP we recognise.";
}
export const UNMATCHED_FIX = "Check the spelling, or try a nearby city.";
