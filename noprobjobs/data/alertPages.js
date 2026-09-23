/* Single source of truth for the alert-signup guide pages (/alerts/{market}/{slug}/).
   Everything that LINKS to them reads THIS module — the WA lander's "job guides" section, the site
   footer, and the /alerts/{market}/ index hub — so adding a page or a whole new geo updates every
   surface at once. build.mjs bakes each entry as a route (plus one index page per market);
   alerts.js holds the per-page CONTENT keyed by `slug`.

   To add a page: add an entry here + its CONTENT in alerts.js PAGES.
   To add a geo: add a market to ALERT_MARKETS + its pages here (state = the state code) + a lander.

   `state` is the state code the slice runs against; `category` is the board category to scope by,
   OR `employers` for a SECTOR page that isn't a board category (Healthcare). `label` is the short
   display name used on cards; `iconCat` (optional) is the category value for the icon lookup. */
export const ALERT_MARKETS = {
  washington: { code: "WA", name: "Washington", landerPath: "/washington-jobs/" },
};

export const ALERT_PAGES = [
  { state: "WA", marketSlug: "washington", slug: "retail", label: "Retail", iconCat: "Retail",
    category: "Retail", path: "/alerts/washington/retail/",
    title: "Retail Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Retail jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "food-services", label: "Food Service", iconCat: "Food Services",
    category: "Food Services", path: "/alerts/washington/food-services/",
    title: "Food Service Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Food service jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "security", label: "Security", iconCat: "Security",
    category: "Security", path: "/alerts/washington/security/",
    title: "Security Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Security jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "warehouse", label: "Warehouse", iconCat: "Warehouse",
    category: "Warehouse", path: "/alerts/washington/warehouse/",
    title: "Warehouse Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Warehouse jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "grocery", label: "Grocery", iconCat: "Grocery",
    category: "Grocery", path: "/alerts/washington/grocery/",
    title: "Grocery Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Grocery jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "transportation-automotive", label: "Driving & Automotive", iconCat: "Transportation/Automotive",
    category: "Transportation/Automotive", path: "/alerts/washington/transportation-automotive/",
    title: "Driving & Automotive Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Driving and automotive jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "sales", label: "Sales", iconCat: "Sales",
    category: "Sales", path: "/alerts/washington/sales/",
    title: "Sales Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Sales jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  { state: "WA", marketSlug: "washington", slug: "facilities", label: "Facilities", iconCat: "Facilities",
    category: "Facilities", path: "/alerts/washington/facilities/",
    title: "Facilities Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Facilities jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
  // Healthcare is a SECTOR, not a board category — scoped by employer (see build.mjs alertSlice).
  { state: "WA", marketSlug: "washington", slug: "healthcare", label: "Hospital & Healthcare", iconCat: null,
    employers: ["multicare.org"], path: "/alerts/washington/healthcare/",
    title: "Hospital & Healthcare Jobs, No Experience Needed | Washington | NoProbJobs",
    description: "Non-clinical hospital and healthcare jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer." },
];

export function pagesForMarket(marketSlug){ return ALERT_PAGES.filter((p) => p.marketSlug === marketSlug); }
export function marketIndexPath(marketSlug){ return "/alerts/" + marketSlug + "/"; }
export function marketBySlug(marketSlug){ return ALERT_MARKETS[marketSlug] || null; }
// The market a given page path belongs to (for a market-aware footer link). Falls back to the sole
// launched market so single-geo pages still get a valid "job guides" link.
export function marketSlugForPath(pathname){
  const m = /\/alerts\/([^/]+)\//.exec(pathname || "");
  if (m && ALERT_MARKETS[m[1]]) return m[1];
  const keys = Object.keys(ALERT_MARKETS);
  return keys.length === 1 ? keys[0] : null;
}
