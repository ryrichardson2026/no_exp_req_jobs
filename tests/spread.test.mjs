/* Tests for R.spreadByEmployer (the per-employer listing-view spread cap).
   Dependency-free: run with `node tests/spread.test.mjs`. record.js is plain ESM.

   NEVER assert "no more than cap_n CONSECUTIVE" — that is provably false here (step-C
   drain intentionally produces runs longer than cap_n). Every assertion below is about
   per-page COUNT, or about total/permutation/determinism. */

import { spreadByEmployer, employerSlug } from "../noprobjobs/data/record.js";

let failures = 0;
function ok(cond, msg){ if (cond) { console.log("  ✓ " + msg); } else { failures++; console.error("  ✗ " + msg); } }
function eq(a, b, msg){ ok(a === b, msg + "  (got " + a + ", want " + b + ")"); }

// A minimal record: identity + the two employer fields keyOf reads. internal_id makes the
// input order explicit (the real comparator's stable tiebreak); spread must never reorder
// within a permutation beyond the documented page/overflow moves.
let _seq = 0;
function rec(company, domain){ return { internal_id: "r" + (_seq++), company_name: company, employer_domain: domain }; }
function many(company, domain, k){ const a = []; for (let i = 0; i < k; i++) a.push(rec(company, domain)); return a; }

// Count of a given tenant (by employer_domain) on page one.
function domCount(page, domain){ return page.filter((r) => r.employer_domain === domain).length; }
// Count of a given brand (by company_name) on page one.
function brandCount(page, name){ return page.filter((r) => r.company_name === name).length; }

const TENANT3 = { key: "tenant", n: 3, scope: "page" };
const BRAND3 = { key: "brand", n: 3, scope: "page" };

// ── Fixture A — diversity regime (distinct_employers × cap_n >= PER_PAGE) ───────────
// Enough distinct employers to fill the page under the cap → the HARD assertion holds:
// the dominant tenant's page-one count is <= cap_n.
(function fixtureA(){
  console.log("Fixture A — diversity regime (hard cap holds):");
  const per = 10; // distinct=4, 4×3=12 >= 10  ✓ diversity
  const kroger = [...many("Fred Meyer", "kroger.com", 5), ...many("Quality Food Centers", "kroger.com", 3)]; // 8, dominant
  const ranked = [...kroger, ...many("Target", "target.com", 5), ...many("Dollar General", "dollargeneral.com", 5), ...many("Sherwin-Williams", "sherwin-williams.com", 5)];
  const before = ranked.length;
  const out = spreadByEmployer(ranked, TENANT3, per);
  const page1 = out.slice(0, per);
  eq(out.length, before, "total count unchanged");
  ok(domCount(page1, "kroger.com") <= TENANT3.n, "dominant tenant page-one count <= cap_n (=" + domCount(page1, "kroger.com") + ")");
  // permutation check: same multiset out as in
  ok(JSON.stringify([...ranked].map(r=>r.internal_id).sort()) === JSON.stringify(out.map(r=>r.internal_id).sort()), "output is a permutation (nothing dropped/duplicated)");
})();

// ── Fixture B — scarcity regime (distinct_employers × cap_n < PER_PAGE) ─────────────
// The cap CANNOT fill the page, so step C drains over-cap cards. Assert ONLY: total
// unchanged, and the dominant tenant's page-one count is STRICTLY BELOW its uncapped
// page-one count (reduced, but may still exceed cap_n). Do NOT assert <= cap_n here.
(function fixtureB(){
  console.log("Fixture B — scarcity regime (soft cap, strictly reduced):");
  const per = 10; // distinct=2, 2×3=6 < 10  → scarcity
  const ranked = [...many("Fred Meyer", "kroger.com", 10), ...many("Target", "target.com", 5)];
  const uncappedPage1 = domCount(ranked.slice(0, per), "kroger.com"); // = 10 (all of page one)
  const out = spreadByEmployer(ranked, TENANT3, per);
  const page1 = out.slice(0, per);
  const cappedPage1 = domCount(page1, "kroger.com");
  eq(out.length, ranked.length, "total count unchanged");
  ok(cappedPage1 < uncappedPage1, "dominant page-one count strictly below uncapped (" + cappedPage1 + " < " + uncappedPage1 + ")");
  eq(page1.length, per, "page still fills to PER_PAGE via drain (never short when supply exists)");
})();

// ── Two-employer category → page still fills to PER_PAGE (scarcity instance) ────────
(function twoEmployer(){
  console.log("Two-employer category (fills the page):");
  const per = 20;
  const ranked = [...many("Alpha", "alpha.com", 15), ...many("Beta", "beta.com", 15)]; // 30 total
  const out = spreadByEmployer(ranked, TENANT3, per);
  eq(out.length, 30, "total count unchanged");
  eq(out.slice(0, per).length, per, "page one fills to 20 (cap is a spreading rule, not a ceiling)");
})();

// ── Single-employer category → byte-identical to the uncapped input ────────────────
// The page is PER_PAGE consecutive cards from one employer — correct, intended output,
// and precisely why a "no more than cap_n consecutive" assertion would be wrong.
(function singleEmployer(){
  console.log("Single-employer category (byte-identical):");
  const per = 10;
  const ranked = many("Solo", "solo.com", 25);
  const out = spreadByEmployer(ranked, TENANT3, per);
  ok(JSON.stringify(out) === JSON.stringify(ranked), "output deep-equals uncapped input (no reordering)");
})();

// ── Determinism → same input twice, identical output ───────────────────────────────
(function determinism(){
  console.log("Determinism:");
  const per = 10;
  const build = () => { _seq = 1000; return [...many("Fred Meyer", "kroger.com", 6), ...many("Target", "target.com", 4), ...many("Dollar General", "dollargeneral.com", 4)]; };
  const a = spreadByEmployer(build(), TENANT3, per);
  const b = spreadByEmployer(build(), TENANT3, per);
  ok(JSON.stringify(a) === JSON.stringify(b), "identical output on repeat runs");
})();

// ── Tenant vs brand → key controls joint vs separate capping ───────────────────────
// Diversity regime for BOTH modes so no drain muddies the count.
// tenant mode: distinct = {kroger, target, dg} = 3, 3×3=9 >= 9
// brand  mode: distinct = {fred-meyer, quality-food-centers, target, dg} = 4, 4×3=12 >= 9
(function tenantVsBrand(){
  console.log("Tenant vs brand key:");
  const per = 9;
  // Kroger front-loaded and interleaved across its two brands.
  const ranked = [];
  for (let i = 0; i < 4; i++) { ranked.push(rec("Fred Meyer", "kroger.com")); ranked.push(rec("Quality Food Centers", "kroger.com")); }
  ranked.push(...many("Target", "target.com", 4), ...many("Dollar General", "dollargeneral.com", 4));

  const tPage1 = spreadByEmployer(ranked, TENANT3, per).slice(0, per);
  const bPage1 = spreadByEmployer(ranked, BRAND3, per).slice(0, per);

  eq(employerSlug("Fred Meyer"), "fred-meyer", "employerSlug sanity (Fred Meyer)");
  eq(employerSlug("Quality Food Centers"), "quality-food-centers", "employerSlug sanity (QFC)");
  eq(domCount(tPage1, "kroger.com"), TENANT3.n, "tenant key caps FM+QFC JOINTLY at cap_n (=" + domCount(tPage1, "kroger.com") + ")");
  const brandKroger = brandCount(bPage1, "Fred Meyer") + brandCount(bPage1, "Quality Food Centers");
  eq(brandKroger, BRAND3.n * 2, "brand key caps EACH Kroger brand separately (2×cap_n=" + brandKroger + ")");
  ok(domCount(tPage1, "kroger.com") < brandKroger, "tenant grouping shows fewer Kroger cards than brand grouping");
})();

console.log("");
if (failures) { console.error(failures + " assertion(s) FAILED"); process.exit(1); }
console.log("All assertions passed.");
