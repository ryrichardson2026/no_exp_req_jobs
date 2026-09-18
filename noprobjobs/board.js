/* Job board. One responsive layout chosen from a matchMedia breakpoint: a two-pane
   list+detail above it, a single column with a filter drawer and full-page job below.
   No inline record contract, no inline resolver, no description pipeline — all from the
   shared modules. No logo loader, no preview props, no frame chrome. */
import { h, s, raw } from "./ui/h.js";
import { Header } from "./ui/header.js";
import { JobCard } from "./ui/jobCard.js";
import { JobPage } from "./ui/jobPage.js";
import { FilterPanel } from "./ui/filterPanel.js";
import { track, sourcePage } from "./ui/track.js";
import { description } from "./data/describe.js";
import * as R from "./data/record.js";
import * as L from "./data/resolve.js";
import * as SB from "./data/supabase.js";
import { EMPLOYER_CAP } from "./data/cap.js";
// Location data is STATIC (not a dynamic import) so resolveLocation works on the FIRST render.
// When it was deferred, a URL like ?location=Seattle applied before cities loaded, so
// resolveLocation("Seattle", [], …) returned "unmatched" → an empty-list flash until cities
// arrived. Combined ~26KB, loaded in parallel with board.js/react — off the critical path.
import { CITIES } from "./data/cities.js";
import { ZIPS } from "./data/zips.js";
import { CITY_GEO } from "./data/cities-geo.js";
import * as RT from "./data/routes.js";
import * as PM from "./data/pageMeta.js";

const React = window.React;
const BP = "(min-width:900px)";
const PRODUCT = "NoProbJobs.com";
const PER_PAGE = 10;

/* Compact numbered window: first, last, current ±1, with a gap where the run skips. */
function pageWindow(cur, total){
  const keep = {};
  [1, total, cur - 1, cur, cur + 1].forEach((n) => { if (n >= 1 && n <= total) keep[n] = 1; });
  const nums = Object.keys(keep).map(Number).sort((a, b) => a - b);
  const out = [];
  let prev = 0;
  nums.forEach((n) => { if (n - prev > 1) out.push("gap"); out.push(n); prev = n; });
  return out;
}

// filter-bar chevrons (desktop pills)
const CHEV = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const CHEV_MUTED = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="var(--ink-muted)" stroke-width="1.6" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
// Right chevron — drill-in rows (Employer / Employment type) in the mobile filter page.
const CHEV_RIGHT = '<svg width="7" height="11" viewBox="0 0 7 11" fill="none" stroke="currentColor" stroke-width="1.8" style="flex:none" aria-hidden="true"><path d="M1.5 1.5 5.5 5.5l-4 4"></path></svg>';
const CHECK14 = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" style="flex:none" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';
const SORT_ICON = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--ink-muted)" stroke-width="1.7" aria-hidden="true"><path d="M4.4 2.6v10.8"></path><path d="M1.8 10.8l2.6 2.6 2.6-2.6"></path><path d="M9.4 5.2h4.8"></path><path d="M9.4 9h3"></path></svg>';
const SEARCH_ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.6"></circle><path d="M10.4 10.4l3.4 3.4"></path></svg>';
const X_SMALL = '<svg width="10" height="10" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M1.6 1.6l11.8 11.8"></path><path d="M13.4 1.6L1.6 13.4"></path></svg>';
const FILTERS_ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 4.2h12"></path><path d="M4.4 8h7.2"></path><path d="M6.6 11.8h2.8"></path></svg>';
const FILTERS_ICON_MUTED = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="var(--ink-muted)" stroke-width="1.8" aria-hidden="true"><path d="M2 4.2h12"></path><path d="M4.4 8h7.2"></path><path d="M6.6 11.8h2.8"></path></svg>';
const CLOSE = '<svg width="13" height="13" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1.6 1.6l11.8 11.8"></path><path d="M13.4 1.6L1.6 13.4"></path></svg>';
const CLOSE15 = '<svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1.6 1.6l11.8 11.8"></path><path d="M13.4 1.6L1.6 13.4"></path></svg>';
// Pixel-art thumbs up for the signup confirmation (matches the landing + the hero star).
// Shown in the detail pane while jobs_detail (description_html) is fetched on open. A
// multi-line skeleton (not a bare "Loading…") so the pane holds roughly a paragraph of
// height and the real description doesn't pop in from a single line — no jump on arrival.
const DESC_LOADING = h("div", { role: "status", "aria-label": "Loading description",
    style: s("display:grid;gap:11px;padding:4px 0;max-width:60ch") },
  [96, 88, 92, 74, 90, 84, 62, 80, 68].map((w, i) =>
    h("div", { key: i, style: s("height:13px;width:" + w + "%;background:var(--surface-sunk);border-radius:3px;animation:sk 1.4s ease-in-out infinite") })));
// Leading chevron for the standalone page's destination back-link.
const BACK_CHEV = '<svg width="9" height="15" viewBox="0 0 9 15" fill="none" stroke="currentColor" stroke-width="2" style="flex:none" aria-hidden="true"><path d="M7.5 1.5 2 7.5l5.5 6"></path></svg>';

class BoardApp extends React.Component {
  constructor(props){
    super(props);
    // A job URL (/jobs/{slug}) loaded COLD renders the FULL board — same chrome, same panel as
    // an in-board click — with the requested job's detail SEEDED from props.openJob so it paints
    // immediately, and the list a skeleton until jobs_list hydrates. No headless page. Decided
    // once from the entry URL, so the first render already carries the panel + chrome. In-board
    // browsing never sets _jobPage — clicking a card there opens the panel via the normal
    // jobs_detail path, untouched. _initialJobId scopes the baked-description reuse + no-fetch to
    // the ENTRY job only: opening a different job from the (now-loaded) list fetches normally.
    this._jobPage = false;
    try { this._jobPage = RT.parsePath(window.location.pathname).kind === "job"; } catch (e) {}
    this._openJob = props.openJob || null;                        // seed record for the panel (no description_html)
    this._initialJobId = this._openJob ? this._openJob.internal_id : null;
    this.state = { openId: this._initialJobId, recs: props.initialRecs || null, logoOk: {}, details: props.initialDetails || {}, stateCtx: null,
      cities: CITIES, zips: ZIPS, cityGeo: CITY_GEO, cats: [], catDraft: [], loc: "", locDraft: "", radius: 15,
      // Experience defaults to OFF (owner decision 2026-09): the board lands showing BOTH
      // no-experience-required AND experience-preferred-not-required — the full board (experience-
      // REQUIRED never reaches it, filtered upstream). Toggling the green band ON narrows to
      // no-experience only. Absence of ?exp = this default (off); ?exp=none = the no-experience view.
      showsPay: false, shifts: [], types: [], exps: [], employers: [], sheet: null, filterSub: null, sort: "newest", pg: 1,
      // Alert capture: email + a required ZIP/city + an optional multi-select of work types
      // (same categories as the board's Work Type filter). alertCatOpen = the job-type dropdown.
      alertsOpen: false, alertEmail: "", alertZip: "", alertCats: [], alertCatOpen: false,
      alertPhase: "form", alertError: "",
      wide: window.matchMedia(BP).matches };
  }

  // ── state changes: every filter/sort resets to page one ──────────────
  setSort = (id) => () => { this.setState({ sort: id, sheet: null, openId: null, pg: 1 }); this.writeUrl({ sort: id, openId: null, page: 1 }); };
  toggleIn(key, value){
    const cur = this.state[key] || [];
    const next = cur.indexOf(value) >= 0 ? cur.filter((v) => v !== value) : cur.concat([value]);
    const over = {}; over[key] = next; over.openId = null; over.page = 1;
    const st = {}; st[key] = next; st.openId = null; st.pg = 1;
    this.setState(st); this.writeUrl(over);
  }
  toggleCat = (c) => () => this.toggleIn("cats", c);
  // Type-of-work menu draft: selections stay pending until Apply (B1). Dismissing the
  // menu (X / click-outside / Escape) never commits; the next open re-inits from cats,
  // so an un-applied draft is discarded.
  toggleCatDraft = (c) => () => {
    const cur = this.state.catDraft || [];
    const next = cur.indexOf(c) >= 0 ? cur.filter((v) => v !== c) : cur.concat([c]);
    this.setState({ catDraft: next });
  };
  clearCatDraft = () => this.setState({ catDraft: [] });
  applyCat = () => {
    const next = (this.state.catDraft || []).slice();
    this.writeUrl({ cats: next, openId: null, page: 1 });
    const t = this._trigger;
    this.setState({ cats: next, openId: null, pg: 1, sheet: null }, () => { if (t && t.isConnected) t.focus(); this._trigger = null; });
  };
  toggleShift = (s2) => () => this.toggleIn("shifts", s2);
  toggleType = (t) => () => this.toggleIn("types", t);
  toggleExp = (e2) => () => this.toggleIn("exps", e2);
  toggleEmployer = (slug) => () => this.toggleIn("employers", slug);
  // "Apply all" select-all checkboxes for the multi-select menus. Category rides the draft
  // (committed by the menu's Apply); shift/type apply live like their individual options.
  selectAllCatDraft = () => this.setState((st) => ({ catDraft: (st.catDraft || []).length === R.CATEGORIES.length ? [] : R.CATEGORIES.slice() }));
  selectAllShifts = () => { const n = this.state.shifts.length === R.SHIFT_FACETS.length ? [] : R.SHIFT_FACETS.slice(); this.setState({ shifts: n, openId: null, pg: 1 }); this.writeUrl({ shifts: n, openId: null, page: 1 }); };
  selectAllTypes = () => { const n = this.state.types.length === R.TYPE_FACETS.length ? [] : R.TYPE_FACETS.slice(); this.setState({ types: n, openId: null, pg: 1 }); this.writeUrl({ types: n, openId: null, page: 1 }); };
  selectAllExps = () => { const n = this.state.exps.length === R.EXP_FACETS.length ? [] : R.EXP_FACETS.slice(); this.setState({ exps: n, openId: null, pg: 1 }); this.writeUrl({ exps: n, openId: null, page: 1 }); };
  // Mobile flagship toggle (the product's whole promise): a clean binary — on = no-experience
  // ONLY (exps=["none"]), off = no experience filter. Reuses the Item 8 exp filter so it stays
  // in sync with the Filters drawer and the ?exp=none URL.
  toggleNoExp = () => { const on = this.state.exps.length === 1 && this.state.exps[0] === "none"; const n = on ? [] : ["none"]; this.setState({ exps: n, openId: null, pg: 1 }); this.writeUrl({ exps: n, openId: null, page: 1 }); };
  // Employer list is dynamic (from the live set), so "Apply all" is computed from recs, not a const.
  selectAllEmployers = () => { const slugs = [...new Set((this.state.recs || []).map((r) => R.employerSlug(r.company_name)).filter(Boolean))]; const n = this.state.employers.length === slugs.length ? [] : slugs; this.setState({ employers: n, openId: null, pg: 1 }); this.writeUrl({ employers: n, openId: null, page: 1 }); };
  togglePay = () => { const v = !this.state.showsPay; this.setState({ showsPay: v, openId: null, pg: 1 }); this.writeUrl({ showsPay: v, openId: null, page: 1 }); };
  // Live select-all for the mobile Work Type list (the page applies filters live, unlike the
  // desktop popover's draft+Apply). Toggles between all categories and none.
  selectAllCatsLive = () => { const n = (this.state.cats || []).length === R.CATEGORIES.length ? [] : R.CATEGORIES.slice(); this.setState({ cats: n, openId: null, pg: 1 }); this.writeUrl({ cats: n, openId: null, page: 1 }); };
  clearAll = () => {
    // Reset to the board's defaults — experience returns to NONE_NEEDED only (the baseline the
    // green band states), not "all". Every other filter clears. (One Clear-all path; see B-report.)
    this.setState({ cats: [], catDraft: [], loc: "", locDraft: "", showsPay: false, shifts: [], types: [], exps: [], employers: [], openId: null, sheet: null, filterSub: null, pg: 1 });
    this.writeUrl({ cats: [], loc: "", showsPay: false, shifts: [], types: [], exps: [], employers: [], openId: null, page: 1 });
  };
  openSheet = (which) => (e) => {
    this._trigger = e && e.currentTarget ? e.currentTarget : null;
    // Mobile has no per-section popovers — only the Sort menu and the full filter page. Route any
    // section request (strip controls, and the empty-state "Change X" CTAs that share `narrowing`)
    // into the full page: as a drill-in for Employer / Employment type, else scrolled to the section.
    if (!this.state.wide && which !== "sort") {
      const sub = (which === "emp" || which === "type") ? which : null;
      this._filterScrollTo = sub || which === "all" ? null : which;
      this.setState({ sheet: "all", filterSub: sub, locDraft: this.state.loc, catDraft: (this.state.cats || []).slice() });
      return;
    }
    this.setState({ sheet: which, locDraft: this.state.loc, catDraft: (this.state.cats || []).slice() });
  };
  closeSheet = () => { const t = this._trigger; this.setState({ sheet: null, filterSub: null }, () => { if (t && t.isConnected) t.focus(); this._trigger = null; }); };
  // Strip controls open the full mobile filter page (sheet "all"); `scrollTo` lands it on a
  // section (Location is first, so it opens at top). Filters inside apply LIVE — the sticky
  // "See N jobs" footer states the outcome and closing commits any pending location draft.
  openFilterPage = (scrollTo) => this.openSheet(scrollTo || "all");
  openSub = (which) => () => this.setState({ filterSub: which });   // drill-in (Employer / Employment type)
  closeSub = () => this.setState({ filterSub: null });
  setFilterScroller = (el) => { if (el) this._filterScroller = el; };
  setSecRef = (key) => (el) => { this._secRef = this._secRef || {}; if (el) this._secRef[key] = el; };
  onLocDraft = (e) => this.setState({ locDraft: e.target.value });
  onLocKey = (e) => { if (e.key === "Enter") { e.preventDefault(); this.applyLoc()(); } };
  // Filter-page location apply: commit the draft but KEEP the page open (unlike applyLoc, which
  // closes its popover). Radius applies live via setRadius, which already leaves the page open.
  applyLocStay = () => { const v = this.state.locDraft; this.setState({ loc: v, openId: null, pg: 1 }); this.writeUrl({ loc: v, openId: null, page: 1 }); };
  onLocKeyStay = (e) => { if (e.key === "Enter") { e.preventDefault(); this.applyLocStay(); } };
  // "See N jobs" — commit any pending location draft, then close the page.
  applyAndClose = () => { if (this.state.locDraft !== this.state.loc) this.applyLocStay(); this.closeSheet(); };
  applyLoc = (value) => () => { const v = value === undefined ? this.state.locDraft : value; this.setState({ loc: v, locDraft: v, sheet: null, openId: null, pg: 1 }); this.writeUrl({ loc: v, openId: null, page: 1 }); };
  clearLoc = () => { this.setState({ loc: "", locDraft: "", openId: null, pg: 1 }); this.writeUrl({ loc: "", openId: null, page: 1 }); };
  setRadius = (r) => () => { this.setState({ radius: r, pg: 1 }); this.writeUrl({ radius: r, page: 1 }); };
  // Desktop inline location field: explicit commit only (parity with mobile's Apply). Enter commits
  // via onLocKeyStay; the inline magnifier commits via applyLocStay. Blur does NOT commit and typing
  // does not filter live — a typed value only applies once the user submits it.
  setLocInput = (el) => { if (el) this._locInput = el; };
  focusLocField = () => { if (this._locInput) { this._locInput.focus(); this._locInput.select(); } };
  setPage = (n) => () => {
    this.setState({ pg: n }, () => { if (this._desk) this._desk.scrollTop = 0; if (this._list) this._list.scrollTop = 0; });
    this.writeUrl({ page: n });
  };

  buildPager(cur, total){
    if (total <= 1) return null;
    const mk = (label, o) => React.createElement("button", Object.assign({
      type: "button", key: o.key,
      style: Object.assign({ minWidth: "44px", minHeight: "44px", boxSizing: "border-box", padding: "0 10px",
        border: "1px solid var(--ink)", borderRadius: "3px", fontFamily: "inherit", fontSize: "14px", fontWeight: 700,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        cursor: o.disabled ? "default" : "pointer",
        background: o.current ? "var(--ink)" : "var(--surface-raised)",
        color: o.current ? "var(--accent-ink)" : "var(--ink)", opacity: o.disabled ? 0.4 : 1 }, o.style || {}),
    }, o.disabled ? { disabled: true } : { onClick: o.onClick }, o.current ? { "aria-current": "page" } : {}, o.ariaLabel ? { "aria-label": o.ariaLabel } : {}), label);
    const kids = [];
    kids.push(mk("‹", { key: "prev", disabled: cur <= 1, onClick: this.setPage(cur - 1), ariaLabel: "Previous page" }));
    pageWindow(cur, total).forEach((it, i) => {
      if (it === "gap") kids.push(React.createElement("span", { key: "g" + i, "aria-hidden": "true", style: { minWidth: "16px", textAlign: "center", color: "var(--ink-muted)", fontWeight: 700 } }, "…"));
      else kids.push(mk(String(it), { key: "p" + it, current: it === cur, onClick: this.setPage(it), ariaLabel: "Page " + it }));
    });
    kids.push(mk("›", { key: "next", disabled: cur >= total, onClick: this.setPage(cur + 1), ariaLabel: "Next page" }));
    return React.createElement("nav", { "aria-label": "Pagination",
      style: { display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center", justifyContent: "center", padding: "14px 16px", borderTop: "1px solid var(--line)", background: "var(--surface-raised)" } }, kids);
  }

  // ── URL state (filters, sort, page, open job) ────────────────────────
  readUrl(){
    let u; try { u = new URL(window.location.href); } catch (e) { return {}; }
    const p = u.searchParams;
    const out = {};
    // canonical path: /jobs/{slug}-{id} (job) or /{state}/{category}/ (browse)
    const route = RT.parsePath(u.pathname);
    if (route.kind === "job") out._jobRef = (route.jobNumber !== undefined) ? { jobNumber: route.jobNumber } : { internalId: route.internalId };
    else if (route.kind === "browse") { out.stateCtx = route.state; if (route.category) out.cats = [route.category]; }
    // legacy ?job=nxj_… (pre-D1 / a shared preview link); resolved + canonicalised on load
    const legacyJob = p.get("job");
    // ?job= takes a job_number (numeric, how the landing deep-links into the board) or a
    // legacy internal_id (nxj_…, a pre-D1 shared link). Resolved to a record + panel on load.
    if (legacyJob && !out._jobRef) out._jobRef = /^\d+$/.test(legacyJob) ? { jobNumber: parseInt(legacyJob, 10) } : { internalId: legacyJob };
    // query refinements (and legacy ?category=, which is multi-select anyway)
    const listOf = (key, allowed) => String(p.get(key) || "").split(",").map((v) => v.trim()).filter((v) => allowed.indexOf(v) >= 0);
    const qcats = listOf("category", R.CATEGORIES);
    if (qcats.length && !out.cats) out.cats = qcats;
    out.shifts = listOf("shift", R.SHIFT_FACETS);
    out.types = listOf("type", R.TYPE_FACETS);
    // exp default (board-wide): NO ?exp param -> [] (OFF = no exp filter, shows none + preferred).
    // ?exp=none -> the no-experience-only view; ?exp=preferred, ?exp=none,preferred parse as before;
    // ?exp=all (legacy) filters to no allowed facet -> [] = same as the default. Default URL stays clean.
    const expParam = p.get("exp");
    out.exps = (expParam === null) ? [] : listOf("exp", R.EXP_FACETS);
    out.employers = String(p.get("emp") || "").split(",").map((v) => v.trim()).filter(Boolean);   // dynamic set; validated by matching in derive
    out.showsPay = p.get("pay") === "1";
    const loc = p.get("location");
    if (loc) { out.loc = loc; out.locDraft = loc; }
    const r = parseInt(p.get("radius"), 10);
    if (L.RADII.indexOf(r) >= 0) out.radius = r;
    const sort = p.get("sort");
    if (R.SORTS.some((s2) => s2.id === sort)) out.sort = sort;
    const pg = parseInt(p.get("page"), 10);
    if (pg >= 1) out.pg = pg;
    return out;
  }
  syncUrl(id){ this.writeUrl({ openId: id }, !!id); }   // opening a job pushes a history entry; closing replaces
  writeUrl(over, push){
    const o = over || {};
    const pick = (k) => (o[k] !== undefined ? o[k] : this.state[k]);
    const job = o.openId !== undefined ? o.openId : this.state.openId;
    const page = o.page !== undefined ? o.page : this.state.pg;
    try {
      let path;
      const q = new URLSearchParams();
      if (job) {
        // Flat, clean canonical job URL — nothing derived, no query refinements.
        const rec = (this.state.recs || []).find((r) => r.internal_id === job);
        path = rec ? RT.jobPath(rec) : "/jobs/";
      } else {
        // Browse: state (per the path context) + a SINGLE category in the path;
        // everything else is a query refinement and stays off the canonical route.
        const cats = pick("cats") || [];
        path = RT.browsePath(pick("stateCtx"), cats.length === 1 ? cats[0] : null);
        if (cats.length > 1) q.set("category", cats.join(","));
        const loc = pick("loc"); if (loc) q.set("location", loc);
        const radius = pick("radius"); if (loc && /^\d{5}$/.test(loc)) q.set("radius", String(radius));
        if (pick("showsPay")) q.set("pay", "1");
        const shifts = pick("shifts") || []; if (shifts.length) q.set("shift", shifts.join(","));
        const types = pick("types") || []; if (types.length) q.set("type", types.join(","));
        // exp: the default is now OFF ([] = no exp filter), so omit the param for the empty set to
        // keep the canonical URL clean; any narrowing (toggle on -> ["none"], or a drawer facet
        // pick) is written explicitly, e.g. ?exp=none or ?exp=none,preferred.
        const exps = pick("exps") || [];
        if (exps.length) q.set("exp", exps.join(","));
        const employers = pick("employers") || []; if (employers.length) q.set("emp", employers.join(","));
        const sort = pick("sort"); if (sort && sort !== "newest") q.set("sort", sort);
        if (page > 1) q.set("page", String(page));
      }
      const qs = q.toString();
      const url = path + (qs ? "?" + qs : "") + window.location.hash;
      // pushState only when a job OPENS, so browser Back returns to the list (items 10/11);
      // filters/sort/page changes and mount canonicalisation replaceState (no extra entries).
      if (push) window.history.pushState({ panel: true }, "", url);
      else window.history.replaceState(null, "", url);
    } catch (e) { /* sandboxed */ }
  }

  // ── focus management for sheets / popovers ───────────────────────────
  panelEl(){ return document.querySelector("[data-filter-pop]") || document.querySelector("[data-filter-drawer]"); }
  focusables(el){
    if (!el) return [];
    return Array.prototype.slice.call(el.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])')).filter((n) => n.offsetParent !== null);
  }
  focusIntoPanel(tries){
    const n = tries || 0;
    if (n > 24 || !this.state.sheet) return;
    const panel = this.panelEl();
    if (panel && panel.contains(document.activeElement)) return;
    const items = this.focusables(panel);
    const real = items.filter((el) => !/^close/i.test(el.getAttribute("aria-label") || ""))[0];
    if (real) real.focus();
    if (!(panel && panel.contains(document.activeElement))) requestAnimationFrame(() => this.focusIntoPanel(n + 1));
  }
  trapTab(e){
    const panel = this.panelEl();
    const items = this.focusables(panel);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (!panel || !panel.contains(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // ── lifecycle ────────────────────────────────────────────────────────
  componentDidMount(){
    this._wasOpen = this.state.openId; this._wasSheet = null;
    window.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("mousedown", this.onDocDown, true);
    this._mql = window.matchMedia(BP);
    this._onMql = () => this.setState({ wide: this._mql.matches });
    this._mql.addEventListener("change", this._onMql);
    // Back/forward: re-derive board state from the URL so Back from a job returns to the
    // filtered list in the state it was left (item 10), not out of the board. Job-opens are
    // pushState entries (see writeUrl); the list entry below still carries its filter query.
    this._onPop = () => {
      const u = this.readUrl();
      const jobRef = u._jobRef; delete u._jobRef;
      let openId = null;
      if (jobRef) { const rec = (this.state.recs || []).find((r) => jobRef.internalId ? r.internal_id === jobRef.internalId : r.job_number === jobRef.jobNumber); openId = rec ? rec.internal_id : null; }
      this.setState(Object.assign({ stateCtx: null, cats: [], shifts: [], types: [], exps: [], employers: [], loc: "", locDraft: "", showsPay: false, sort: "newest", pg: 1, sheet: null, filterSub: null }, u, { openId }));
    };
    window.addEventListener("popstate", this._onPop);
    const urlState = this.readUrl();
    this.setState(urlState);
    // Arrivals from an expired/retired page carry ?alerts=1 (+ the job's cat/city): open the
    // email-only modal and stash the context so submitAlerts captures it silently (change #1
    // kept the RPC's category/location args; only the form stopped collecting them). Opened via
    // setState post-mount, so baked pages (which never carry ?alerts) keep baked/mounted parity.
    try {
      const ap = new URL(window.location.href).searchParams;
      if (ap.get("alerts") === "1") {
        this._alertCtx = { cat: ap.get("cat") || null, city: ap.get("city") || null };
        track({ event: "job_alert_open", source_page: sourcePage() });
        this.setState({ alertsOpen: true, alertPhase: "form", alertError: "",
          // Prefill the form fields from the expired/retired job's context.
          alertZip: this._alertCtx.city || "", alertCats: this._alertCtx.cat ? [this._alertCtx.cat] : [] });
      }
    } catch (e) {}
    // Alert-intent weighting (see landing.js): a completed search WITH a location is full
    // intent, so arriving on the board with a location seeds the counter by one; job views
    // (open()) add the rest. The prompt is only ever evaluated inside open(), so the modal
    // still cannot fire before a job has been viewed — a chip tap never counts.
    this._opens = urlState.loc ? 1 : 0;
    const jobRef = urlState._jobRef || null;
    SB.pulledAt().then((d) => R.setToday(d)).catch(() => {});
    // resolve the URL ref -> a record -> openId (internal_id, the app's key). Prefer
    // job_number; fall back to a legacy internal_id ref for the transition. Then canonicalise
    // (legacy id / ?job= / ?category= -> the path form).
    const resolve = (recs) => {
      let openId = null;
      if (jobRef) {
        const rec = jobRef.internalId
          ? recs.find((r) => r.internal_id === jobRef.internalId)
          : recs.find((r) => r.job_number === jobRef.jobNumber);
        openId = rec ? rec.internal_id : null;
      }
      this.setState({ recs, openId }, () => this.writeUrl({}));
      this.preflightLogos(recs);
    };
    if (this.state.recs) resolve(this.state.recs);            // seeded at mount — no refetch, no wipe
    else SB.listJobs().then(resolve).catch((e) => { console.error("jobs_list failed to load", e); this.setState({ recs: [] }); });
    // Job page: kick the entry job's description fetch now so the BAKE populates [data-desc-html]
    // deterministically (WAIT.job gates on it, and jobs_list is withheld during a job-route bake).
    // At runtime BAKED_DESC is set, so ensureDetail skips this — no round trip.
    if (this._jobPage && this._initialJobId) this.ensureDetail(this._initialJobId);
    this.syncDocTitle();
  }
  // C1: push the state-derived title (computed in derive(), stashed on _docTitle) to the tab. Skip
  // on a standalone /jobs page — its baked <title> is the SEO title and must not be JS-overwritten.
  syncDocTitle(){
    if (this._jobPage || !this._docTitle) return;
    try { if (document.title !== this._docTitle) document.title = this._docTitle; } catch (e) {}
  }
  componentDidUpdate(prevProps, prevState){
    const wasOpen = prevState ? prevState.openId : this._wasOpen;
    this._wasOpen = this.state.openId;
    const wasSheet = prevState ? prevState.sheet : this._wasSheet;
    this._wasSheet = this.state.sheet;
    if (this.state.sheet && wasSheet !== this.state.sheet) this.focusIntoPanel();
    // Mobile filter page: land on the section the strip control asked for (Work Type opens mid-page;
    // Location is first, so it opens at top with no scroll). Deferred past focusIntoPanel's rAF.
    if (this.state.sheet === "all" && wasSheet !== "all" && this._filterScrollTo) {
      const key = this._filterScrollTo; this._filterScrollTo = null;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const el = this._secRef && this._secRef[key];
        if (el && el.scrollIntoView) { try { el.scrollIntoView({ block: "start" }); } catch (e) {} }
      }));
    }
    if (wasOpen && !this.state.openId) {
      const restore = () => { const node = this._scrollNode || this._list; if (node) node.scrollTop = this._scroll || 0; };
      restore(); requestAnimationFrame(restore);
    }
    // The detail pane shows the open job (or, on desktop, the first of the page). Its
    // description_html isn't in jobs_list, so fetch jobs_detail for whichever job is
    // effective now (derive() stashed its id). Cached + de-duped in ensureDetail.
    this.ensureDetail(this._effectiveId);
    this.syncDocTitle();
  }

  ensureDetail(id){
    if (!id || (this.state.details && this.state.details[id])) return;
    // Job page, ENTRY job only: its description_html is baked and rendered from BAKED_DESC (see
    // mount), so the jobs_detail fetch would only re-fetch on-screen content. Skip it. A DIFFERENT
    // job opened from the list has no baked description, so it falls through and fetches.
    if (this._jobPage && BAKED_DESC && id === this._initialJobId) return;
    this._detailPending = this._detailPending || {};
    if (this._detailPending[id]) return;
    this._detailPending[id] = true;
    SB.jobDetail(id).then((d) => {
      if (d) this.setState((st) => { const nx = Object.assign({}, st.details); nx[id] = d; return { details: nx }; });
    }).catch((e) => console.error("jobs_detail failed", id, e))
      .then(() => { delete this._detailPending[id]; });
  }
  componentWillUnmount(){
    window.removeEventListener("keydown", this.onKeyDown);
    window.removeEventListener("mousedown", this.onDocDown, true);
    if (this._onPop) window.removeEventListener("popstate", this._onPop);
    if (this._mql) this._mql.removeEventListener("change", this._onMql);
    clearTimeout(this._t);
  }

  preflightLogos(recs){
    const seen = {};
    recs.forEach((r) => {
      if (R.localLogo(r.company_name)) return;   // hand-picked local logo shows directly — no favicon probe
      const d = r.employer_domain;
      if (!d || seen[d] || !R.ownsDomain(r.company_name, d)) return;
      seen[d] = true;
      const img = new Image();
      img.onerror = () => {};
      img.onload = () => { if (img.naturalWidth < 16) return; this.setState((st) => { const ok = Object.assign({}, st.logoOk); ok[d] = true; return { logoOk: ok }; }); };
      img.src = R.logoUrl(d);
    });
  }

  setListEl = (el) => { if (el) this._list = el; };
  setDeskEl = (el) => { if (el) this._desk = el; };

  // ── alerts modal ─────────────────────────────────────────────────────
  ALERT_KEY = "npj.alerts.dismissed";
  readFlag(){ if (this._flag !== undefined) return this._flag; try { this._flag = window.localStorage.getItem(this.ALERT_KEY) === "1"; } catch (e) { this._flag = false; } return this._flag; }
  writeFlag(){ this._flag = true; try { window.localStorage.setItem(this.ALERT_KEY, "1"); } catch (e) {} }
  // Change #1: email-only — opening no longer pre-fills location/categories (fields gone).
  // Change #5: fire job_alert_open on open (covers the header CTA and the empty-state CTA,
  // both of which route their click through here).
  openAlerts = () => {
    track({ event: "job_alert_open", source_page: sourcePage() });
    this.setState({ alertsOpen: true, alertPhase: "form", alertError: "", alertCatOpen: false });
  };
  closeAlerts = () => { this.writeFlag(); clearTimeout(this._alertT); this.setState({ alertsOpen: false, alertCatOpen: false }); };
  onAlertEmail = (e) => this.setState({ alertEmail: e.target.value });
  onAlertZip = (e) => this.setState({ alertZip: e.target.value });
  toggleAlertCatOpen = () => this.setState({ alertCatOpen: !this.state.alertCatOpen });
  toggleAlertCat = (c) => () => {
    const cur = this.state.alertCats || [];
    const next = cur.indexOf(c) >= 0 ? cur.filter((x) => x !== c) : cur.concat([c]);
    this.setState({ alertCats: next });
  };
  selectAllAlertCats = () => {
    const all = (this.state.alertCats || []).length === R.CATEGORIES.length;
    this.setState({ alertCats: all ? [] : R.CATEGORIES.slice() });
  };
  submitAlerts = () => {
    const email = (this.state.alertEmail || "").trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { this.setState({ alertPhase: "form", alertError: "Enter a valid email address." }); return; }
    const location = (this.state.alertZip || "").trim();
    if (!location) { this.setState({ alertPhase: "form", alertError: "Enter a ZIP code or city." }); return; }
    const categories = this.state.alertCats || [];   // optional refinement (job types)
    this.setState({ alertPhase: "creating", alertError: "", alertCatOpen: false });
    const wait = new Promise((r) => { this._alertT = setTimeout(r, 2500); });   // deliberate 2.5s "Creating alert" loader
    // capture_alert is a fixed 4-arg RPC (no defaults): the form now collects the location
    // (required) and work-type categories (optional); an expired/retired arrival still routes
    // as "expired". The columns/signature are untouched.
    const ctx = this._alertCtx || null;   // set when arriving from an expired/retired page (?alerts=1)
    Promise.all([SB.captureAlert({ email, source: ctx ? "expired" : "board", categories, location }), wait])
      .then(() => { track({ event: "email_capture_submit", source_page: sourcePage() }); this.writeFlag(); this.setState({ alertPhase: "done" }); })
      .catch(() => this.setState({ alertPhase: "form", alertError: "Couldn’t save that — please try again." }));
  };
  onAlertKey = (e) => { if (e.key === "Enter") { e.preventDefault(); this.submitAlerts(); } };

  open(r){
    return (e) => {
      if (e && e.preventDefault) e.preventDefault();   // the card is an <a href>; open the panel instead of navigating
      const node = (e && e.currentTarget && e.currentTarget.closest("[data-list-scroller]")) || this._list;
      this._scrollNode = node; this._scroll = node ? node.scrollTop : 0;
      this._opens = (this._opens || 0) + 1;
      const prompt = this._opens >= 3 && !this.readFlag() && !this.state.alertsOpen;
      const st = { openId: r.internal_id };
      // Auto-prompt after the 3rd open. It's an automatic open, not a user click, so it does
      // NOT push job_alert_open (that event tracks intentional opens via the CTAs / openAlerts).
      if (prompt) Object.assign(st, { alertsOpen: true, alertPhase: "form", alertError: "" });
      this.setState(st);
      this.syncUrl(r.internal_id);
    };
  }
  back = () => {
    // If the panel was opened with a pushed history entry, pop it so browser + in-app back
    // agree and the popstate handler restores the filtered list. Otherwise (a cold arrival
    // that opened the panel at mount, replaceState) just close it in place.
    if (window.history.state && window.history.state.panel) { window.history.back(); return; }
    this.setState({ openId: null }); this.syncUrl(null);
  };

  onDocDown = (e) => {
    const st = this.state.sheet;
    if (!st || st === "all") return;
    const t = e.target;
    if (t && t.closest && (t.closest("[data-filter-pop]") || t.closest("[data-filter-trigger]"))) return;
    this.closeSheet();
  };
  onKeyDown = (e) => {
    if (e.key === "Tab" && this.state.sheet) { this.trapTab(e); return; }
    if (e.key !== "Escape") return;
    if (this.state.sheet) { e.preventDefault(); this.closeSheet(); return; }
    if (this.state.openId) { e.preventDefault(); this.back(); }
  };

  shape(r){
    const domain = r.employer_domain || "";
    // A hand-picked local logo wins over the domain favicon (and bypasses ownsDomain,
    // which is exactly why Fred Meyer/QFC on kroger.com get their real mark now).
    const local = R.localLogo(r.company_name);
    const logoSrc = local || R.logoUrl(domain);
    const showLogo = local ? true : (R.ownsDomain(r.company_name, domain) && !!this.state.logoOk[domain]);
    return Object.assign({}, r, {
      id: r.internal_id,
      company: R.companyLabel(r.company_name),
      cardTitle: R.cardTitle(r.title),
      logoImg: showLogo ? R.logoImg(logoSrc, 20) : null,
      logoSrc: showLogo ? logoSrc : null,   // dense card builds its own <img> (onError → monogram)
      pageLogoImg: showLogo ? R.logoImg(logoSrc, 24) : null,
      showLogo, showMonogram: !showLogo,
      monogram: (r.company_name || "?").trim().charAt(0).toUpperCase(),
      locationLine: [L.cityName(r.city), r.state].filter(Boolean).join(", "),
      pay: R.money(r), posted: R.postedLabel(r.posted_at), isNew: !!r.is_new,
      expLabel: R.EXP_LABEL[r.experience_condition] || null,
      expStrong: r.experience_condition === "NONE_NEEDED" || r.experience_condition === "WAIVED",
      expSoft: r.experience_condition === "PREFERRED",
      isSelected: this.state.openId === r.internal_id,
      href: RT.jobPath(r) + "/",              // real crawlable link (canonical, trailing slash)
      onCardClick: this.open(r),              // intercepts the link -> opens the panel in-app
      open: this.open(r),
      openKey: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.open(r)(e); } },
    });
  }

  // ── derive everything the layout needs from state ────────────────────
  derive(){
    const st = this.state;
    const recs = st.recs;
    const loading = recs === null;
    const all = recs || [];
    const cats = st.cats || [], shifts = st.shifts || [], types = st.types || [], exps = st.exps || [], employers = st.employers || [];
    const noExpOn = exps.length === 1 && exps[0] === "none";        // green-band switch: on = no-experience only
    const expIsDefault = exps.length === 0;                          // baseline (new default = toggle OFF: none + preferred)
    const res = L.resolveLocation(st.loc, st.cities, st.zips);
    const radius = st.radius;
    const inLoc = (r) => {
      if (res.kind === "all") return true;
      if (res.kind === "state") return r.state === res.state;
      if (res.kind === "city") return res.cities.indexOf(L.cityKey(r.city)) >= 0;
      if (res.kind === "zip") {
        const at = (r.lat != null && r.lng != null) ? [r.lat, r.lng] : (st.cityGeo || {})[L.cityKey(r.city)];
        return !!at && L.haversine(res.centroid, at) <= radius;
      }
      return false;
    };
    const inCat = (r) => !cats.length || R.recordCats(r).some((c) => cats.indexOf(c) >= 0);
    const inPay = (r) => !st.showsPay || !!r.salary_is_stated;
    const inShift = (r) => !shifts.length || R.shiftFacets(r.shift_raw).some((f) => shifts.indexOf(f) >= 0);
    const inType = (r) => !types.length || types.indexOf(R.typeFacet(r.employment_type)) >= 0;
    const inExp = (r) => !exps.length || exps.indexOf(R.expFacet(r.experience_condition)) >= 0;
    const inEmp = (r) => !employers.length || employers.indexOf(R.employerSlug(r.company_name)) >= 0;

    const ranked = all.filter((r) => inCat(r) && inLoc(r) && inPay(r) && inShift(r) && inType(r) && inExp(r) && inEmp(r)).sort(R.COMPARATORS[st.sort] || R.newestFirst);
    // Presentation-only per-employer spread cap (item: grocery-fold fix). Reorders the ranked
    // list so one tenant can't own the top of a page; drops nothing, so `total` is unchanged.
    const list = R.spreadByEmployer(ranked, EMPLOYER_CAP, PER_PAGE);
    const total = list.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    const pg = Math.min(Math.max(1, st.pg || 1), totalPages);
    const start = (pg - 1) * PER_PAGE;
    const pageRecs = list.slice(start, start + PER_PAGE);

    const availUnder = (skip) => all.filter((r) =>
      (skip === "cat" || inCat(r)) && (skip === "loc" || inLoc(r)) && (skip === "pay" || inPay(r)) && (skip === "shift" || inShift(r)) && (skip === "type" || inType(r)) && (skip === "exp" || inExp(r)) && (skip === "emp" || inEmp(r)));
    const shiftPool = availUnder("shift"), typePool = availUnder("type"), expPool = availUnder("exp"), locPool = availUnder("loc"), empPool = availUnder("emp");

    const opt = (label, on, avail, pick) => ({ label, isOn: on, isOff: !on && avail, isUnavailable: !on && !avail, pick });
    const catOptions = R.CATEGORIES.map((c) => opt(c, cats.indexOf(c) >= 0, true, this.toggleCat(c)));
    const catDraft = st.catDraft || [];
    const catDraftOptions = R.CATEGORIES.map((c) => opt(c, catDraft.indexOf(c) >= 0, true, this.toggleCatDraft(c)));
    const shiftOptions = R.SHIFT_FACETS.map((s2) => opt(s2, shifts.indexOf(s2) >= 0, shiftPool.some((r) => R.shiftFacets(r.shift_raw).indexOf(s2) >= 0), this.toggleShift(s2)));
    const typeOptions = R.TYPE_FACETS.map((t) => opt(t, types.indexOf(t) >= 0, typePool.some((r) => R.typeFacet(r.employment_type) === t), this.toggleType(t)));
    const expOptions = R.EXP_FACETS.map((e2) => opt(R.EXP_FACET_LABEL[e2], exps.indexOf(e2) >= 0, expPool.some((r) => R.expFacet(r.experience_condition) === e2), this.toggleExp(e2)));
    // Employer options are dynamic: every employer in the live set (item 13), alphabetical,
    // no counts. Brands are their own company_names, so this lists brands, not a parent.
    const empSeen = {};
    all.forEach((r) => { const g = R.employerSlug(r.company_name); if (g && !(g in empSeen)) empSeen[g] = R.companyLabel(r.company_name); });
    const empEntries = Object.keys(empSeen).map((g) => ({ slug: g, label: empSeen[g] })).sort((a, b) => a.label.localeCompare(b.label));
    const employerOptions = empEntries.map((e2) => opt(e2.label, employers.indexOf(e2.slug) >= 0, true, this.toggleEmployer(e2.slug)));

    const draft = L.cityKey(st.locDraft);
    const isZipDraft = /^\d{5}$/.test(draft);
    const locCities = {};
    locPool.forEach((r) => { locCities[L.cityKey(r.city)] = 1; });
    const cityOptions = (st.cities || []).filter((c) => locCities[L.cityKey(c.city)])
      .filter((c) => !draft || isZipDraft || L.cityKey(c.city).indexOf(draft) === 0)
      .map((c) => ({ city: c.city, state: c.state, label: L.cityName(c.city) + ", " + c.state, pick: this.applyLoc(c.city), isCurrent: res.kind === "city" && res.cities.indexOf(L.cityKey(c.city)) >= 0 }));

    const locLabel = res.kind === "all" ? null
      : res.kind === "zip" ? res.zip + " · " + radius + " mi"
      : res.kind === "state" ? res.state
      : res.kind === "city" ? (res.display.length > 1 ? res.display[0] + " +" + (res.display.length - 1) : res.display[0])
      : st.loc;
    const listOf = (arr) => (arr.length > 2 ? arr.slice(0, 2).join(", ") + " +" + (arr.length - 2) : arr.join(", "));

    const narrowing = [];
    if (shifts.length) narrowing.push({ label: "Shift", fix: "Clear the shift filter — most postings don’t state a shift.", open: this.openSheet("shift") });
    if (types.length) narrowing.push({ label: "Employment type", fix: "Clear the employment type filter.", open: this.openSheet("type") });
    if (exps.length) narrowing.push({ label: "Experience", fix: "Clear the experience filter.", open: this.openSheet("exp") });
    if (employers.length) narrowing.push({ label: "Employer", fix: "Clear the employer filter or add another employer.", open: this.openSheet("emp") });
    if (st.showsPay) narrowing.push({ label: "Shows pay", fix: "Turn off Shows pay — most employers don’t state pay.", open: null });
    // Desktop has no loc popover (the field is inline in the bar), so the empty-state fix focuses
    // that field; mobile still routes to the full filter page via openSheet.
    if (res.kind !== "all") narrowing.push({ label: "Location", fix: "Try a wider radius, or a different city.", open: st.wide ? this.focusLocField : this.openSheet("loc") });
    if (cats.length) narrowing.push({ label: "Work Type", fix: "Add another work type.", open: this.openSheet("cat") });

    // On a cold job page the list is a skeleton (recs still loading), so the open job isn't in
    // `all` yet — fall back to the seeded panel record so the panel paints immediately. Once
    // jobs_list hydrates, the record resolves from `all` as normal.
    let openRec = all.find((r) => r.internal_id === st.openId)
      || (this._openJob && this._openJob.internal_id === st.openId ? this._openJob : null)
      || pageRecs[0] || null;
    const effectiveId = openRec ? openRec.internal_id : null;
    this._effectiveId = effectiveId;                 // componentDidUpdate fetches its detail
    const det = effectiveId ? (st.details || {})[effectiveId] : null;
    if (openRec && det) openRec = Object.assign({}, openRec, det);   // merge description_html
    const detailReady = !!det;
    const onPage = !!st.openId && !!openRec;
    // Expired = the employer actually removed it (churn: the latest pull for its source
    // didn't see it), NOT merely posted long ago. freshness_state STALE is an age LABEL
    // ("Posted 2 months ago") and a sort signal; a 30-day-old posting still present in the
    // pull is live and still accepting, so it keeps its Apply button and its JobPosting.
    const expired = openRec ? !!openRec.expired : false;
    let page = { modifiers: [], live: !expired, expired };
    if (openRec) {
      const mods = [];
      if (openRec.employment_type) mods.push({ value: openRec.employment_type, isType: true });
      if (openRec.shift_raw) mods.push({ value: R.shiftLabel(openRec.shift_raw), isShift: true });
      if (openRec.fte) mods.push({ value: (+(openRec.fte * 100).toFixed(1)) + "% of full-time hours", isFte: true });
      page = Object.assign(this.shape(openRec), {
        description: detailReady ? description(openRec)
          : (this._jobPage && BAKED_DESC && st.openId === this._initialJobId ? raw(BAKED_DESC) : DESC_LOADING), modifiers: mods, hasFacts: mods.length > 0,
        expVerbatim: R.verbatim(openRec),
        verbatimNeedsLabel: openRec.experience_condition === "PREFERRED" && !!R.verbatim(openRec),
        verbatimBare: openRec.experience_condition === "WAIVED" && !!R.verbatim(openRec),
        hasModifiers: mods.length > 0 || !!R.postedLabel(openRec.posted_at) || !!R.EXP_LABEL[openRec.experience_condition],
        expired, live: !expired, applyUrl: openRec.apply_url || null,
        // Change #5: payload for the apply_click dataLayer push, fired from the Apply link in
        // jobPage.js. job_id prefers the public job_number, falls back to internal_id.
        applyEvt: { job_id: openRec.job_number != null ? openRec.job_number : openRec.internal_id,
          employer: R.companyLabel(openRec.company_name), category: R.recordCats(openRec)[0] || null },
      });
    }

    const unmatched = res.kind === "unmatched" || res.kind === "unmatched-zip";
    const locResolved = res.kind !== "all" && !unmatched;
    const first = narrowing[0];
    const emptyLine = unmatched ? L.unmatchedLine(res, st.loc)
      : first && first.label === "Location" && res.kind === "city" ? "No jobs in " + res.display[0] + "."
      : first ? "No jobs match " + first.label.toLowerCase() + "."
      : "No jobs right now.";
    const emptyFix = unmatched ? L.UNMATCHED_FIX
      : res.kind === "zip" && radius < 25 && first && first.label === "Location" ? "Widen the radius to 25 miles, or try a nearby city."
      : first ? first.fix : "Check back later.";

    const locEmptyName = res.kind === "zip" ? res.zip : res.kind === "state" ? res.state : res.kind === "city" ? res.display[0] : st.loc;
    const realEmpty = !loading && total === 0;
    const locEmpty = realEmpty && locResolved;
    const genericEmpty = realEmpty && !locEmpty;
    const elsewhereRecs = locEmpty ? R.spreadByEmployer(all.filter((r) => inCat(r) && inPay(r) && inShift(r) && inType(r)).sort(R.COMPARATORS[st.sort] || R.newestFirst), EMPLOYER_CAP, PER_PAGE).slice(0, PER_PAGE) : [];
    const elsewhereJobs = elsewhereRecs.map((r) => this.shape(r));
    const elsewhereHeading = cats.length ? "Jobs elsewhere in " + listOf(cats) : "Newest jobs";

    // §4 fade: replay on a user-triggered filter/sort/page change via list remount key.
    const sig = JSON.stringify([cats, st.loc, radius, st.showsPay, shifts, types, exps, employers, st.sort, pg]);
    if (this._sig === undefined) this._sig = sig;
    else if (sig !== this._sig) { this._sig = sig; this._animEpoch = (this._animEpoch || 0) + 1; this._animOn = true; }

    // C1: document.title reflects the SPA state so tabs, bookmarks and shared links aren't all the
    // generic board title. Precedence: open job wins, else active filters (category/location/no-exp),
    // else the baked default. Applied in componentDidMount/Update, and ONLY on the board SPA — a
    // standalone /jobs page keeps its baked SEO title. Copy formats are owner-approved.
    const DEFAULT_TITLE = "Get Hired Now - No Experience Needed | NoProbJobs";
    let docTitle = DEFAULT_TITLE;
    if (onPage && page && page.title) {
      const cityST = [L.cityName(openRec.city), openRec.state].filter(Boolean).join(" ");   // "Shelton WA"
      const emp = page.company ? page.company + (cityST ? ", " + cityST : "") : "";
      docTitle = page.title + (emp ? " | " + emp : "") + " | NoProbJobs";
    } else {
      const catPart = cats.length ? (cats.length === 1 ? cats[0] : cats[0] + " & more") : null;
      let locPart = null, near = false;
      if (res.kind === "zip") { locPart = res.zip; near = true; }
      else if (res.kind === "state") locPart = res.state;
      else if (res.kind === "city") {
        const cs = (st.cities || []).find((c) => L.cityKey(c.city) === (res.cities && res.cities[0]));
        locPart = res.display[0] + (cs && cs.state ? ", " + cs.state : "");
      }
      let base = null;
      if (near) base = (catPart ? catPart + " jobs" : "Jobs") + " near " + locPart;
      else if (catPart && locPart) base = catPart + " jobs in " + locPart;
      else if (locPart) base = "Jobs in " + locPart;
      else if (catPart) base = catPart + " jobs";
      else if (exps.length === 1 && exps[0] === "none") base = "No-experience jobs";
      if (base) docTitle = base + " | NoProbJobs";
    }
    this._docTitle = docTitle;

    return {
      loading, list, total, totalPages, pg, pageRecs, res, radius, isZipDraft,
      catOptions, catDraftOptions, shiftOptions, typeOptions, expOptions, employerOptions, cityOptions, locLabel, listOf,
      catAllOn: catDraft.length === R.CATEGORIES.length,
      shiftAllOn: shifts.length === R.SHIFT_FACETS.length,
      typeAllOn: types.length === R.TYPE_FACETS.length,
      expAllOn: exps.length === R.EXP_FACETS.length,
      employerAllOn: employers.length === empEntries.length,
      cats, shifts, types, exps, employers,
      catLabel: cats.length ? listOf(cats) : null,
      // Mobile chip: first selection plus a count, never concatenated names that get
      // cut mid-word at 390px (B4). One selection shows its name alone.
      catChipLabel: cats.length ? (cats.length > 1 ? cats[0] + " +" + (cats.length - 1) : cats[0]) : null,
      shiftLabel: shifts.length ? listOf(shifts) : null,
      typeLabel: types.length ? listOf(types) : null,
      expLabel: exps.length ? listOf(exps.map((e2) => R.EXP_FACET_LABEL[e2])) : null,
      employerLabel: employers.length ? listOf(employers.map((s2) => empSeen[s2] || s2)) : null,
      // Experience defaults to OFF (exps empty), so an empty set is the baseline, NOT a refinement.
      // anyFilter (Clear/Reset visibility) counts experience only when it narrows (exps non-empty).
      anyFilter: !!(cats.length || res.kind !== "all" || st.showsPay || shifts.length || types.length || employers.length || !expIsDefault),
      extraCount: (shifts.length ? 1 : 0) + (types.length ? 1 : 0) + (exps.length ? 1 : 0) + (employers.length ? 1 : 0) + (st.showsPay ? 1 : 0),
      // Mobile Filters badge — count of active groups NOT surfaced on their own control (location,
      // experience, and Job type each have a dedicated strip control / band, so they're excluded).
      filtersBadge: (shifts.length ? 1 : 0) + (types.length ? 1 : 0) + (employers.length ? 1 : 0) + (st.showsPay ? 1 : 0),
      noExpOn: noExpOn,   // green-band switch state: on = no-experience only (default is now OFF)
      resultLabelShort: total === 1 ? "1 job" : total + " jobs",
      sortLabel: (R.SORTS.find((s2) => s2.id === st.sort) || R.SORTS[0]).label,
      sortOptions: R.SORTS.map((s2) => ({ label: s2.label, isCurrent: s2.id === st.sort, notCurrent: s2.id !== st.sort, pick: this.setSort(s2.id) })),
      radiusOptions: L.RADII.map((r) => ({ label: r + " mi", value: r, isOff: !isZipDraft, isOnCurrent: isZipDraft && r === radius, isOnOther: isZipDraft && r !== radius, pick: this.setRadius(r) })),
      radiusInactive: !isZipDraft,
      hasLoc: !!st.loc, unmatched, locResolved,
      unmatchedLine: L.unmatchedLine(res, st.loc) + " " + L.UNMATCHED_FIX,
      noCityMatch: !!draft && !isZipDraft && cityOptions.length === 0,
      noCityMatchLine: "No city starting with “" + st.locDraft + "” has jobs under the filters you’ve set.",
      openRec, effectiveId, onPage, page,
      resultLabel: total === 1 ? "1 job found" : total + " jobs found",
      browseH1: st.stateCtx
        ? (cats.length === 1 ? PM.categoryH1(cats[0], st.stateCtx) : PM.stateH1(st.stateCtx))
        : "Get hired now, no experience needed",
      isLoading: loading, isList: !loading && total > 0, realEmpty, locEmpty, genericEmpty, locEmptyName,
      elsewhereJobs, hasElsewhere: elsewhereJobs.length > 0, elsewhereHeading,
      emptyLine, emptyFix,
      emptyCtaLabel: first ? "Change " + first.label.toLowerCase() : "Clear filters",
      emptyCta: first ? (first.open || this.togglePay) : this.clearAll,
      hasEmptyCta: !!first,
      pager: this.buildPager(pg, totalPages),
      animKey: "list-" + (this._animEpoch || 0), animClass: this._animOn ? "list-fade" : undefined,
      deskJobs: pageRecs.map((r) => Object.assign(this.shape(r), { isSelected: r.internal_id === effectiveId })),
      jobs: pageRecs.map((r) => this.shape(r)),
    };
  }

  // ── list body (loading / locEmpty / genericEmpty / list+pager) ───────
  listBody(d, wide){
    if (d.isLoading) return h("div", null, [1,2,3,4,5,6].slice(0, wide ? 6 : 5).map((k) => h("div", { key: k, style: s("padding:16px;border-bottom:1px solid var(--line);display:grid;gap:9px;animation:sk 1.4s ease-in-out infinite") },
      h("div", { style: s("height:11px;width:" + (wide ? "26%" : "38%") + ";background:var(--surface-sunk);border-radius:3px") }),
      h("div", { style: s("height:18px;width:" + (wide ? "64%" : "82%") + ";background:var(--surface-sunk);border-radius:3px") }),
      h("div", { style: s("height:13px;width:" + (wide ? "38%" : "52%") + ";background:var(--surface-sunk);border-radius:3px") }),
      h("div", { style: s("height:13px;width:" + (wide ? "30%" : "44%") + ";background:var(--surface-sunk);border-radius:3px") }))));
    if (d.locEmpty) return h("div", null,
      h("div", { style: s(wide ? "padding:48px 32px 24px;display:grid;gap:8px;justify-items:start" : "padding:40px 24px 20px;display:grid;gap:8px;justify-items:start") },
        h("div", { style: s((wide ? "font-size:19px" : "font-size:17px") + ";font-weight:700;color:var(--ink)") }, "No jobs here yet."),
        h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);max-width:" + (wide ? "40ch" : "32ch") + ";text-wrap:pretty") }, "We’ll email you when jobs are posted near " + d.locEmptyName + "."),
        h("button", { type: "button", onClick: this.openAlerts, style: s("margin-top:8px;min-height:44px;padding:0 18px;border-radius:3px;background:var(--accent);color:var(--accent-ink);border:0;font-size:15px;font-weight:600;cursor:pointer") }, "Get job alerts")),
      d.hasElsewhere && h("div", { key: "elsew" },
        h("div", { style: s("padding:10px " + (wide ? "32px" : "24px") + ";font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;color:var(--ink);background:var(--surface-sunk);border-top:1px solid var(--line);border-bottom:1px solid var(--line)") }, d.elsewhereHeading),
        h("div", { role: "list" }, d.elsewhereJobs.map((job) => h(JobCard, { key: job.id, job, dense: !wide })))));
    if (d.genericEmpty) return h("div", { style: s(wide ? "padding:64px 32px;display:grid;gap:8px;justify-items:start" : "padding:56px 24px;display:grid;gap:8px;justify-items:start") },
      h("div", { style: s((wide ? "font-size:19px" : "font-size:17px") + ";font-weight:700;color:var(--ink)") }, d.emptyLine),
      h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);max-width:" + (wide ? "34ch" : "30ch") + ";text-wrap:pretty") }, d.emptyFix),
      d.hasEmptyCta && h("button", { key: "cta", type: "button", onClick: d.emptyCta, style: s("margin-top:8px;min-height:44px;padding:0 18px;border-radius:3px;background:var(--accent);color:var(--accent-ink);border:0;font-size:15px;font-weight:600;cursor:pointer") }, d.emptyCtaLabel));
    // list — an ItemList (structured data about the LIST, not the jobs): H1 = itemprop
    // name, each card = a ListItem with its rendered position + canonical URL. build.mjs
    // absolutizes the relative itemprop urls at bake time. On a JOB page the list is
    // navigation beside the panel's one JobPosting, not the page's subject — so it carries
    // NO ItemList/ListItem markup (no itemScope, no itemProp name, no per-card listMeta).
    const cards = wide ? d.deskJobs : d.jobs;
    const listItems = h("div", { key: d.animKey, role: "list", className: d.animClass }, cards.map((job, i) => h(JobCard, { key: job.id, job, dense: !wide, listMeta: this._jobPage ? null : { position: i + 1, url: job.href } })));
    // Desktop: the H1 + ItemList itemScope live on the static list header / left column
    // (renderDeskListHeader + renderWide), so here we render only the cards + pager.
    if (wide) return h("div", null, listItems, d.pager);
    const listSchema = this._jobPage ? {} : { itemScope: true, itemType: "https://schema.org/ItemList" };
    const h1Attrs = { style: s("margin:0;padding:14px 16px 8px;font-family:var(--font-display);font-size:19px;line-height:1.15;font-weight:800;letter-spacing:-0.005em;color:var(--ink)") };
    if (!this._jobPage) h1Attrs.itemProp = "name";
    return h("div", listSchema,
      h("h1", h1Attrs, d.browseH1),
      listItems,
      d.pager
    );
  }

  filterProps(d, flags){
    return Object.assign({
      sortOptions: d.sortOptions, catOptions: d.catOptions, shiftOptions: d.shiftOptions, typeOptions: d.typeOptions, expOptions: d.expOptions, employerOptions: d.employerOptions,
      cityOptions: d.cityOptions, radiusOptions: d.radiusOptions, radiusInactive: d.radiusInactive,
      unmatched: d.unmatched, unmatchedLine: d.unmatchedLine, noCityMatch: d.noCityMatch, noCityMatchLine: d.noCityMatchLine,
      locDraft: this.state.locDraft, onLocDraft: this.onLocDraft, onLocKey: this.onLocKey, applyDraft: this.applyLoc(),
      clearLoc: this.clearLoc, hasLoc: d.hasLoc, showsPay: this.state.showsPay, payOff: !this.state.showsPay, togglePay: this.togglePay,
      catAll: this.selectAllCatDraft, catAllOn: d.catAllOn,
      shiftAll: this.selectAllShifts, shiftAllOn: d.shiftAllOn,
      typeAll: this.selectAllTypes, typeAllOn: d.typeAllOn,
      expAll: this.selectAllExps, expAllOn: d.expAllOn,
      employerAll: this.selectAllEmployers, employerAllOn: d.employerAllOn,
    }, flags);
  }

  // ── wide: desktop filter bar + popover ───────────────────────────────
  pill(active, label, onClick, expanded, chevWhite){
    if (active) return h("button", { type: "button", "data-filter-trigger": "true", onClick, "aria-expanded": expanded, "aria-haspopup": "true",
        style: s("min-height:34px;display:flex;align-items:center;gap:6px;padding:0 10px;border:1px solid var(--ink);border-radius:3px;background:var(--ink);font-size:14.5px;font-weight:700;color:var(--accent-ink);cursor:pointer;flex:none") },
      h("span", { style: s("white-space:nowrap") }, label), raw(CHEV));
    return h("button", { type: "button", "data-filter-trigger": "true", onClick, "aria-expanded": expanded, "aria-haspopup": "true", className: "hv-bd-accent",
        style: s("min-height:34px;display:flex;align-items:center;gap:6px;padding:0 10px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:14.5px;font-weight:500;color:var(--ink);cursor:pointer;flex:none") },
      h("span", { style: s("white-space:nowrap") }, label), raw(CHEV_MUTED));
  }
  // Desktop Location — a persistent, always-editable inline field (NOT a dropdown/trigger pill).
  // You type a city/state/ZIP straight into the bar; Enter or blur applies it. A leading red dot +
  // navy border read as APPLIED; for a ZIP the 10/15/25 radius sits inline (default 15). Matches the
  // mobile strip's always-visible "● 98178 · 15 mi" readout — one mental model across devices.
  renderLocField(d){
    const applied = d.locResolved;
    const isZip = d.isZipDraft;
    // Explicit commit: the magnifier shows whenever the draft is non-empty AND not yet the committed
    // value — i.e. there is something to submit. Once committed (draft === applied loc) it gives way
    // to the × clear, so the field never shows both at once. Empty field shows neither.
    const draftRaw = String(this.state.locDraft || "").trim();
    const pending = draftRaw !== "" && draftRaw !== String(this.state.loc || "").trim();
    return h("div", { style: s("flex:none;display:flex;align-items:center;gap:7px;min-height:34px;padding:0 5px 0 9px;border:1px solid " + (applied ? "var(--ink)" : "var(--line)") + ";border-radius:3px;background:var(--surface-raised)") },
      h("span", { "aria-hidden": "true", style: s("flex:none;width:7px;height:7px;border-radius:50%;" + (applied ? "background:var(--accent)" : "background:transparent;box-shadow:inset 0 0 0 1.5px var(--hair)")) }),
      h("input", { type: "text", ref: this.setLocInput, value: this.state.locDraft, onChange: this.onLocDraft, onKeyDown: this.onLocKeyStay,
          placeholder: "City, state or ZIP", "aria-label": "Location — city, state or ZIP",
          style: s("flex:none;width:" + (isZip ? "62px" : "148px") + ";box-sizing:border-box;min-height:30px;padding:0;border:0;background:transparent;font-family:inherit;font-size:14.5px;font-weight:" + (applied ? "700" : "500") + ";color:var(--ink);outline:none") }),
      // Inline radius (ZIP only) — same 10/15/25 set as mobile, applied live; default 15.
      isZip && h("span", { style: s("flex:none;display:flex;align-items:center;gap:2px;padding-left:6px;margin-left:1px;border-left:1px solid var(--line)") },
        L.RADII.map((r, i) => { const cur = r === d.radius; return h("button", { key: i, type: "button", onClick: this.setRadius(r), "aria-pressed": cur, "aria-label": r + " miles",
          style: s("min-height:28px;min-width:25px;padding:0 3px;border-radius:3px;font-size:12.5px;font-weight:" + (cur ? "700" : "500") + ";cursor:pointer;border:1px solid " + (cur ? "var(--ink)" : "transparent") + ";background:" + (cur ? "var(--ink)" : "transparent") + ";color:" + (cur ? "var(--accent-ink)" : "var(--ink-muted)")) }, r); }),
        h("span", { style: s("font-size:12px;color:var(--ink-muted);padding:0 3px 0 1px") }, "mi")),
      // Submit (magnifier) — the explicit commit affordance; shown only while a draft is pending.
      pending && h("button", { type: "button", onClick: this.applyLocStay, "aria-label": "Search this location", className: "hv-bg-sunk-tx-ink",
        style: s("flex:none;width:26px;height:26px;margin-left:1px;display:grid;place-items:center;padding:0;background:transparent;border:0;border-radius:3px;cursor:pointer;color:var(--ink)") }, raw(SEARCH_ICON)),
      // Clear (only when committed & unedited) — keeps the field itself permanent.
      applied && !pending && h("button", { type: "button", onClick: this.clearLoc, "aria-label": "Clear location", className: "hv-bg-sunk-tx-ink",
        style: s("flex:none;width:22px;height:22px;margin-left:1px;display:grid;place-items:center;padding:0;background:transparent;border:0;border-radius:3px;cursor:pointer;color:var(--ink-muted);font-size:17px;line-height:1") }, "×")
    );
  }
  renderFilterBarWide(d){
    const sheet = this.state.sheet;
    // Order matches mobile's strip: Location leads, then Work Type. Sort no longer lives here — it
    // sits in the static list header (renderDeskListHeader), on the "…jobs in Washington" row.
    return h("div", { style: s("flex:none;display:flex;align-items:center;gap:7px;padding:8px 20px;border-bottom:1px solid var(--line);position:relative;z-index:5;flex-wrap:wrap") },
      this.renderLocField(d),
      d.cats.length ? this.pill(true, d.catLabel, this.openSheet("cat"), sheet === "cat") : this.pill(false, "Work Type", this.openSheet("cat"), sheet === "cat"),
      this.state.showsPay
        ? h("button", { type: "button", onClick: this.togglePay, "aria-pressed": true, style: s("min-height:34px;display:flex;align-items:center;gap:6px;padding:0 10px;border:1px solid var(--ink);border-radius:3px;background:var(--ink);font-size:14.5px;font-weight:700;color:var(--accent-ink);cursor:pointer;flex:none") }, raw(CHECK14), h("span", { style: s("white-space:nowrap") }, "Shows pay"))
        : h("button", { type: "button", onClick: this.togglePay, "aria-pressed": false, className: "hv-bd-accent", style: s("min-height:38px;display:flex;align-items:center;padding:0 13px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:14.5px;font-weight:500;color:var(--ink);cursor:pointer;flex:none") }, h("span", { style: s("white-space:nowrap") }, "Shows pay")),
      d.shifts.length ? this.pill(true, d.shiftLabel, this.openSheet("shift"), sheet === "shift") : this.pill(false, "Shift", this.openSheet("shift"), sheet === "shift"),
      d.types.length ? this.pill(true, d.typeLabel, this.openSheet("type"), sheet === "type") : this.pill(false, "Employment type", this.openSheet("type"), sheet === "type"),
      // Experience moved OUT of the filter bar to the green "No experience required" band below
      // (renderExpBand), matching mobile — no experience pill here.
      d.employers.length ? this.pill(true, d.employerLabel, this.openSheet("emp"), sheet === "emp") : this.pill(false, "Employer", this.openSheet("emp"), sheet === "emp"),
      d.anyFilter && h("button", { key: "clr", type: "button", onClick: this.clearAll, className: "hv-tx-accent", style: s("min-height:38px;padding:0 8px;background:transparent;border:0;font-size:14px;font-weight:600;color:var(--accent);cursor:pointer;flex:none") }, "Clear"),
      h("span", { style: s("flex:1") }),
      d.isList && h("span", { key: "rl", style: s("margin-left:auto;font-size:14px;font-weight:600;color:var(--ink)") }, d.resultLabel)
    );
  }
  // Static list header (desktop): the browse H1 on the left, Sort on the right — the row the
  // user asked for, sitting below the green band and above the scrolling list. The H1 carries the
  // ItemList itemProp name (the itemScope wraps this header + the cards, so schema stays intact).
  renderDeskListHeader(d){
    const sheet = this.state.sheet;
    const h1Attrs = { style: s("margin:0;font-family:var(--font-display);font-size:19px;line-height:1.15;font-weight:800;letter-spacing:-0.005em;color:var(--ink)") };
    if (!this._jobPage) h1Attrs.itemProp = "name";
    return h("div", { style: s("flex:none;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 16px 9px;border-bottom:1px solid var(--line);background:var(--surface-raised);position:relative;z-index:4") },
      h("h1", h1Attrs, d.browseH1),
      h("div", { style: s("flex:none;position:relative") },
        h("button", { type: "button", "data-filter-trigger": "true", onClick: this.openSheet("sort"), "aria-expanded": sheet === "sort", "aria-haspopup": "true", className: "hv-bd-accent",
            style: s("min-height:34px;display:flex;align-items:center;gap:6px;padding:0 10px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:14.5px;font-weight:500;color:var(--ink);cursor:pointer") },
          raw(SORT_ICON), h("span", { style: s("white-space:nowrap") }, d.sortLabel)),
        sheet === "sort" && h("div", { "data-filter-pop": "true", role: "dialog", "aria-label": "Sort", style: s("position:absolute;top:calc(100% + 6px);right:0;z-index:20;width:230px;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;box-shadow:0 10px 30px rgba(10,58,117,0.18)") },
          h(FilterPanel, this.filterProps(d, { isSort: true }))))
    );
  }
  // Sticky Apply/Clear footer for the Type-of-work menu (B1). Clear resets the pending
  // selection; Apply commits it. Shared by the desktop popover and the mobile cat sheet
  // so the interaction is learned once.
  applyFooter(){
    return h("div", { key: "apf", style: s("flex:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;border-top:1px solid var(--line);background:var(--surface-raised)") },
      h("button", { type: "button", onClick: this.clearCatDraft, className: "hv-tx-ink", style: s("min-height:44px;padding:0 8px;background:transparent;border:0;font-size:14px;font-weight:600;color:var(--ink-muted);cursor:pointer") }, "Clear"),
      h("button", { type: "button", onClick: this.applyCat, className: "hv-bright", style: s("min-height:44px;padding:0 22px;border-radius:3px;background:var(--accent);border:0;font-size:15px;font-weight:700;color:var(--accent-ink);cursor:pointer") }, "Apply"));
  }
  renderPopover(d){
    const sheet = this.state.sheet;
    // Sort is rendered locally in the list header (renderDeskListHeader), not here; location is an
    // inline bar field. So this popover only serves the left-hand filter pills, all left-aligned.
    if (!sheet || sheet === "all" || sheet === "sort") return null;
    const isCat = sheet === "cat";
    const align = "left:28px";
    return h("div", { "data-filter-pop": "true", role: "dialog", "aria-label": "Filters", style: s("position:absolute;top:50px;" + align + ";z-index:6;width:372px;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;box-shadow:0 12px 32px rgba(10,58,117,0.16);max-height:520px;display:flex;flex-direction:column") },
      h("div", { style: s("flex:none;display:flex;justify-content:flex-end;padding:6px 6px 0") },
        h("button", { type: "button", onClick: this.closeSheet, "aria-label": "Close filter menu", className: "hv-bg-sunk-tx-ink", style: s("width:36px;height:36px;display:grid;place-items:center;background:transparent;border:0;border-radius:3px;cursor:pointer;color:var(--ink-muted)") }, raw(CLOSE))),
      h("div", { style: s("flex:1;min-height:0;overflow-y:auto;margin-top:-8px") },
        h(FilterPanel, this.filterProps(d, { isSort: sheet === "sort", isCat: isCat, isLoc: sheet === "loc", isShift: sheet === "shift", isType: sheet === "type", isExp: sheet === "exp", isEmployer: sheet === "emp", catOptions: d.catDraftOptions }))),
      isCat && this.applyFooter()
    );
  }

  renderWide(d){
    // Change #4: constrain the board to the same centred rail the landing uses (var(--rail),
    // 1040px on desktop via .board-scope). The navy header/footer stay full-bleed (they're
    // outside this container); the filter bar, list and detail pane centre within it. The
    // detail pane's own measure is capped independently at 68ch (see [data-desc-html]).
    return h("div", { style: s("flex:1;min-height:0;width:100%;max-width:var(--rail,1120px);margin:0 auto;display:flex;flex-direction:column;position:relative") },
      this.renderFilterBarWide(d),
      this.renderExpBand(d),          // same green "No experience required" toggle strip as mobile
      this.renderPopover(d),
      h("div", { key: "body", style: s("flex:1;min-height:0;display:flex;background:var(--surface-sunk)") },
        // Left column: itemScope ItemList wrapping the STATIC header (H1 = itemProp name + Sort)
        // and the scrolling card list below it — so the heading + Sort stay put while cards scroll.
        h("div", Object.assign({ style: s("width:436px;flex:none;min-height:0;display:flex;flex-direction:column;background:var(--surface-raised);border-right:1px solid var(--line)") },
            this._jobPage ? {} : { itemScope: true, itemType: "https://schema.org/ItemList" }),
          d.isList && this.renderDeskListHeader(d),
          h("div", { ref: this.setDeskEl, "data-list-scroller": "true", style: s("flex:1;min-height:0;overflow-y:auto") },
            this.listBody(d, true))),
        h("div", { style: s("flex:1;min-width:0;position:relative;background:var(--surface)") },
          d.openRec
            ? h(JobPage, { page: d.page, categories: R.CATEGORIES, back: this.back, isMobilePage: false, isPanel: false, isPermanent: true })
            : h("div", { style: s("position:absolute;inset:0;display:grid;place-content:center;justify-items:center;padding:40px") }, h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-align:center") }, "No job to show.")))
      )
    );
  }

  // ── mobile filter primitives ─────────────────────────────────────────────
  // iOS-style pill switch — the one deliberately rounded control in a hard-cornered UI, because a
  // switch has to read as a switch. `tone:"ok"` uses the palette's green (--ok, reserved for the
  // experience claim); default is the brand red. The 44px hit box wraps a 26px-tall track.
  switchEl(on, onClick, label, tone){
    const track = tone === "ok" ? "var(--ok)" : "var(--accent)";
    return h("button", { type: "button", role: "switch", "aria-checked": on, "aria-label": label, onClick,
        style: s("flex:none;width:48px;height:44px;padding:0;display:grid;place-items:center;background:transparent;border:0;cursor:pointer") },
      h("span", { "aria-hidden": "true", style: s("position:relative;display:block;width:44px;height:26px;border-radius:13px;transition:background 140ms ease;background:" + (on ? track : "var(--hair)")) },
        h("span", { style: s("position:absolute;top:3px;left:" + (on ? "21px" : "3px") + ";width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(10,58,117,0.3);transition:left 140ms ease") })));
  }
  // On/off/unavailable option rendered as a tile (Work Type, Shift, Employment type). Navy fill
  // when on; dashed + dimmed when the current result set has none of it.
  tileOpt(o, i){
    if (o.isUnavailable) return h("button", { key: i, type: "button", disabled: true, "aria-disabled": true,
      style: s("min-height:44px;border-radius:3px;font-size:14px;font-weight:600;cursor:not-allowed;background:var(--surface-raised);border:1px dashed var(--line);color:var(--ink-muted);opacity:0.55;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 4px") }, o.label);
    const on = o.isOn;
    return h("button", { key: i, type: "button", onClick: o.pick, "aria-pressed": on,
      style: s("min-height:44px;border-radius:3px;font-size:14px;font-weight:" + (on ? "700" : "600") + ";cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 4px;background:" + (on ? "var(--ink)" : "var(--surface-raised)") + ";border:1px solid " + (on ? "var(--ink)" : "var(--line)") + ";color:" + (on ? "var(--accent-ink)" : "var(--ink)")) }, o.label);
  }
  // Full-width checkbox row (Employer drill-in list). Whole row is the hit target.
  checkRow(o, i, bold){
    const on = o.isOn;
    return h("button", { key: i, type: "button", role: "checkbox", "aria-checked": on, onClick: o.pick, className: "hv-bg-sunk",
        style: s("width:100%;box-sizing:border-box;min-height:48px;display:flex;align-items:center;gap:11px;padding:0 12px;background:transparent;border:0;font-size:15px;color:var(--ink);cursor:pointer;text-align:left") },
      h("span", { "aria-hidden": "true", style: s("flex:none;width:20px;height:20px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (on ? "var(--ink)" : "var(--line)") + ";background:" + (on ? "var(--ink)" : "var(--surface)")) }, on ? raw(CHECK14) : null),
      h("span", { style: s("flex:1;font-weight:" + (bold ? "700" : (on ? "700" : "500"))) }, o.label));
  }
  // Drill-in row (Employer / Employment type): label left, current value + › right.
  drillRow(label, value, onClick){
    return h("button", { type: "button", onClick,
        style: s("width:100%;box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 12px;min-height:52px;border:0;border-bottom:1px solid var(--line);background:transparent;cursor:pointer;text-align:left") },
      h("span", { style: s("font-size:15px;font-weight:600;color:var(--ink)") }, label),
      h("span", { style: s("display:flex;align-items:center;gap:6px;min-width:0;color:var(--ink-muted)") },
        h("span", { style: s("overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:150px;font-size:14px") }, value), raw(CHEV_RIGHT)));
  }
  // Section shell — tight 10px padding, 13px/500 label + optional hint (the §4 density spec).
  filterSec(key, label, hint, body){
    return h("div", { key: key, ref: this.setSecRef(key), style: s("padding:10px 12px;border-bottom:1px solid var(--line)") },
      h("div", { style: s("display:flex;align-items:baseline;gap:8px;margin-bottom:7px") },
        h("div", { style: s("font-size:13px;font-weight:600;color:var(--ink)") }, label),
        hint && h("span", { style: s("font-size:12px;font-weight:500;color:var(--ink-muted)") }, hint)),
      body);
  }

  // ── mobile: strip (three controls) ───────────────────────────────────────
  renderMobileStrip(d){
    const locActive = d.locResolved;
    const locText = locActive ? d.locLabel : (d.hasLoc ? d.locLabel : "Location");
    return h("div", { className: "brd-fstrip", style: s("flex:none;display:flex;align-items:center;gap:6px;padding:5px 12px;border-bottom:1px solid var(--line);overflow-x:auto;-webkit-overflow-scrolling:touch") },
      // Location — a button (not a raw input): tapping opens the filter page at the Location
      // section, where the ZIP + radius live. Red dot signals a location is set; radius shown inline.
      h("button", { type: "button", onClick: this.openFilterPage("loc"), "aria-label": "Location and radius", className: "hv-bd-accent",
          style: s("flex:1 0 128px;min-width:116px;min-height:44px;display:flex;align-items:center;gap:7px;padding:0 11px;border:1px solid " + (locActive ? "var(--ink)" : "var(--line)") + ";border-radius:3px;background:var(--surface-raised);cursor:pointer;text-align:left") },
        locActive && h("span", { "aria-hidden": "true", style: s("flex:none;width:7px;height:7px;border-radius:50%;background:var(--accent)") }),
        h("span", { style: s("flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;font-weight:" + (locActive ? "700" : "500") + ";color:" + (locActive ? "var(--ink)" : "var(--ink-muted)")) }, locText)),
      // Work Type — opens the filter page at the Work Type section (▾); navy when a type is chosen.
      d.cats.length
        ? h("button", { type: "button", onClick: this.openFilterPage("cat"), "aria-label": "Work Type", style: s("flex:none;min-height:44px;display:flex;align-items:center;gap:5px;padding:0 10px;border:1px solid var(--ink);border-radius:3px;background:var(--ink);font-size:14px;font-weight:700;color:var(--accent-ink);cursor:pointer") }, h("span", { style: s("white-space:nowrap") }, d.catChipLabel), raw(CHEV))
        : h("button", { type: "button", onClick: this.openFilterPage("cat"), "aria-label": "Work Type", className: "hv-bd-accent", style: s("flex:none;min-height:44px;display:flex;align-items:center;gap:5px;padding:0 10px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:14px;font-weight:500;color:var(--ink);cursor:pointer") }, h("span", { style: s("white-space:nowrap") }, "Work Type"), raw(CHEV_MUTED)),
      // Filters — opens the full page. Corner badge counts active groups not surfaced on their own
      // control (location, experience and Work Type each have a dedicated control/band, so excluded).
      d.filtersBadge
        ? h("button", { type: "button", onClick: this.openFilterPage(null), "aria-label": "Filters, " + d.filtersBadge + " active", style: s("flex:none;position:relative;min-height:44px;display:flex;align-items:center;gap:6px;padding:0 11px;border:1px solid var(--ink);border-radius:3px;background:var(--surface-raised);font-size:14px;font-weight:700;color:var(--ink);cursor:pointer") }, raw(FILTERS_ICON), h("span", null, "Filters"),
            h("span", { style: s("position:absolute;top:-7px;right:-7px;min-width:18px;height:18px;box-sizing:border-box;display:grid;place-items:center;padding:0 4px;border-radius:9px;background:var(--accent);color:var(--accent-ink);font-size:11px;font-weight:800;border:1.5px solid var(--surface)") }, d.filtersBadge))
        : h("button", { type: "button", onClick: this.openFilterPage(null), "aria-label": "Filters", className: "hv-bd-accent", style: s("flex:none;min-height:44px;display:flex;align-items:center;gap:6px;padding:0 11px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:14px;font-weight:500;color:var(--ink);cursor:pointer") }, raw(FILTERS_ICON_MUTED), h("span", null, "Filters"))
    );
  }

  // ── mobile: the green Experience band (on by default; one-tap reversible) ──
  renderExpBand(d){
    const on = d.noExpOn;
    return h("div", { key: "expband", style: s("flex:none;display:flex;align-items:center;gap:8px;padding:0 8px 0 12px;min-height:38px;background:var(--ok-soft);border-bottom:1px solid var(--line)") },
      this.switchEl(on, this.toggleNoExp, "No experience required", "ok"),
      h("span", { style: s("flex:1;font-size:14px;font-weight:700;color:var(--ok-ink-text)") },
        "No experience required",
        h("span", { style: s("font-weight:500;opacity:0.85") }, " — " + (on ? "on" : "off"))));
  }

  // ── mobile: full-page filter (own header, own scroll, sticky footer) ──────
  renderFilterPage(d){
    const sub = this.state.filterSub;
    const header = h("div", { style: s("flex:none;display:flex;align-items:center;gap:8px;padding:0 6px;min-height:48px;border-bottom:1px solid var(--line)") },
      h("button", { type: "button", onClick: this.closeSheet, "aria-label": "Close filters", className: "hv-bg-sunk", style: s("flex:none;width:44px;height:44px;display:grid;place-items:center;background:transparent;border:0;border-radius:3px;cursor:pointer;color:var(--ink)") }, raw(CLOSE15)),
      h("span", { style: s("flex:1;text-align:center;font-size:16px;font-weight:800;color:var(--ink)") }, "Filters"),
      h("button", { type: "button", onClick: this.clearAll, style: s("flex:none;min-height:44px;padding:0 12px;background:transparent;border:0;font-size:15px;font-weight:700;color:var(--accent);cursor:pointer") }, "Reset"));

    // Drill-in sub-views replace the section body (a back row + the option list); header/footer stay.
    let body;
    if (sub) {
      const isEmp = sub === "emp";
      body = h("div", { key: "sub", style: s("flex:1;min-height:0;display:flex;flex-direction:column") },
        h("div", { style: s("flex:none;display:flex;align-items:center;padding:0 6px;min-height:48px;border-bottom:1px solid var(--line)") },
          h("button", { type: "button", onClick: this.closeSub, "aria-label": "Back to filters", className: "hv-bg-sunk", style: s("min-height:44px;display:flex;align-items:center;gap:5px;padding:0 8px;background:transparent;border:0;border-radius:3px;cursor:pointer;color:var(--ink);font-size:15px;font-weight:700") }, raw(BACK_CHEV), h("span", null, isEmp ? "Employer" : "Employment type"))),
        h("div", { style: s("flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch") },
          isEmp
            ? h("div", { style: s("padding:4px 0") }, [this.checkRow({ isOn: d.employerAllOn, label: "All employers", pick: this.selectAllEmployers }, "all", true)].concat((d.employerOptions || []).map((e2, i) => this.checkRow(e2, i))))
            : h("div", { style: s("padding:10px 12px") }, h("div", { style: s("display:grid;grid-template-columns:1fr 1fr;gap:6px") }, (d.typeOptions || []).map((t, i) => this.tileOpt(t, i))))));
    } else {
      body = h("div", { key: "main", ref: this.setFilterScroller, style: s("flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch") },
        // Location — ZIP input (navy-filled when it carries a value) + 10/15/25 three-up (default 15).
        this.filterSec("loc", "Location", null, h("div", null,
          h("input", { type: "text", value: this.state.locDraft, onChange: this.onLocDraft, onKeyDown: this.onLocKeyStay, placeholder: "City, state or ZIP", "aria-label": "City, state or ZIP",
            style: s("box-sizing:border-box;width:100%;min-height:44px;padding:0 12px;border:1px solid var(--ink);border-radius:3px;font-size:16px;font-family:inherit;outline:none;" + (this.state.locDraft ? "background:var(--ink);color:#fff" : "background:var(--surface);color:var(--ink)")) }),
          h("div", { style: s("display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:7px") },
            (d.radiusOptions || []).map((r, i) => { const cur = r.value === d.radius; return h("button", { key: i, type: "button", onClick: r.pick, "aria-pressed": cur,
              style: s("min-height:44px;border-radius:3px;font-size:14px;font-weight:" + (cur ? "700" : "600") + ";cursor:pointer;background:" + (cur ? "var(--ink)" : "var(--surface-raised)") + ";border:1px solid " + (cur ? "var(--ink)" : "var(--line)") + ";color:" + (cur ? "var(--accent-ink)" : "var(--ink)")) }, r.label); })),
          d.radiusInactive && h("div", { style: s("margin-top:6px;font-size:12.5px;line-height:1.4;color:var(--ink-muted)") }, "Radius applies to a ZIP code. A city or state name filters to that area."),
          (d.unmatched || d.noCityMatch) && h("div", { style: s("margin-top:7px;font-size:14px;line-height:1.45;color:var(--ink);text-wrap:pretty") }, d.unmatched ? d.unmatchedLine : d.noCityMatchLine))),
        // Experience — no section heading; the row label ("No experience required only") names it.
        // Same NONE_NEEDED-only switch as the board band, in sync.
        h("div", { ref: this.setSecRef("exp"), style: s("display:flex;align-items:center;gap:8px;padding:0 8px 0 12px;min-height:52px;border-bottom:1px solid var(--line)") },
          h("span", { style: s("flex:1;font-size:15px;font-weight:600;color:var(--ink)") }, "No experience required only"),
          this.switchEl(d.noExpOn, this.toggleNoExp, "No experience required only", "ok")),
        // Work Type — all categories as COMPACT small-text checkboxes in two columns (not full-width
        // rows), so the ten fit in ~5 rows instead of consuming the page. Applied live.
        this.filterSec("cat", "Work Type", null, h("div", null,
          h("button", { type: "button", role: "checkbox", "aria-checked": d.cats.length === R.CATEGORIES.length, onClick: this.selectAllCatsLive, className: "hv-bg-sunk",
              style: s("display:flex;align-items:center;gap:8px;min-height:34px;padding:0 5px;margin-bottom:3px;background:transparent;border:0;border-radius:3px;cursor:pointer;font-size:13px;font-weight:700;color:var(--ink)") },
            h("span", { "aria-hidden": "true", style: s("flex:none;width:17px;height:17px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (d.cats.length === R.CATEGORIES.length ? "var(--ink)" : "var(--line)") + ";background:" + (d.cats.length === R.CATEGORIES.length ? "var(--ink)" : "var(--surface)")) }, d.cats.length === R.CATEGORIES.length ? raw(CHECK14) : null),
            h("span", null, "All work types")),
          h("div", { style: s("display:grid;grid-template-columns:1fr 1fr;gap:1px 8px") },
            (d.catOptions || []).map((c, i) => h("button", { key: i, type: "button", role: "checkbox", "aria-checked": c.isOn, onClick: c.pick, className: "hv-bg-sunk",
                style: s("display:flex;align-items:center;gap:7px;min-height:38px;padding:0 4px;background:transparent;border:0;border-radius:3px;cursor:pointer;text-align:left") },
              h("span", { "aria-hidden": "true", style: s("flex:none;width:17px;height:17px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (c.isOn ? "var(--ink)" : "var(--line)") + ";background:" + (c.isOn ? "var(--ink)" : "var(--surface)")) }, c.isOn ? raw(CHECK14) : null),
              h("span", { style: s("flex:1;font-size:13px;font-weight:" + (c.isOn ? "700" : "500") + ";line-height:1.15;color:var(--ink)") }, c.label)))))),
        // Shift — two-up tiles.
        this.filterSec("shift", "Shift", null, h("div", { style: s("display:grid;grid-template-columns:1fr 1fr;gap:6px") }, (d.shiftOptions || []).map((so, i) => this.tileOpt(so, i)))),
        // Low-use groups drill in rather than expanding inline.
        this.drillRow("Employer", d.employers.length ? d.employerLabel : "All", this.openSub("emp")),
        this.drillRow("Employment type", d.types.length ? d.typeLabel : "All", this.openSub("type")),
        // Shows pay only — a switch row.
        h("div", { style: s("display:flex;align-items:center;gap:8px;padding:0 8px 0 12px;min-height:52px;border-bottom:1px solid var(--line)") },
          h("span", { style: s("flex:1;font-size:15px;font-weight:600;color:var(--ink)") }, "Shows pay only"),
          this.switchEl(this.state.showsPay, this.togglePay, "Shows pay only")));
    }

    // Sticky footer — the ONE "Clear all" in the interface + the outcome-stating primary button.
    const footer = h("div", { style: s("flex:none;display:flex;align-items:center;gap:10px;padding:10px 12px;border-top:1px solid var(--line);background:var(--surface)") },
      h("button", { type: "button", onClick: this.clearAll, style: s("flex:none;min-height:44px;padding:0 10px;background:transparent;border:0;font-size:15px;font-weight:700;color:var(--accent);cursor:pointer") }, "Clear all"),
      h("button", { type: "button", onClick: this.applyAndClose, style: s("flex:1;min-height:48px;border-radius:3px;background:var(--accent);border:0;font-size:16px;font-weight:800;color:var(--accent-ink);cursor:pointer") }, "See " + d.total + (d.total === 1 ? " job" : " jobs")));

    return h("div", { key: "fpage", "data-filter-drawer": "true", role: "dialog", "aria-modal": "true", "aria-label": "Filters",
        style: s("position:absolute;inset:0;z-index:8;display:flex;flex-direction:column;background:var(--surface);animation:sheetdown 200ms cubic-bezier(.22,.61,.36,1)") },
      header, body, footer);
  }

  // ── mobile ────────────────────────────────────────────────────────────
  renderMobile(d){
    const sheet = this.state.sheet;
    // brd-body-m: on desktop the STATIC (mobile-baked) HTML shows until React mounts and switches
    // to renderWide. Without this it painted edge-to-edge full-width, then snapped to the centered
    // rail — a "goes wide then centers" jump. Constrain it to the same rail so the outer width is
    // stable across the mobile→desktop handoff. On phones (<768px) the rule is off — full width.
    return h("div", { className: "brd-body-m", style: s("display:flex;flex-direction:column;height:100%;min-height:0;position:relative") },
      // Chrome: strip (three controls) + green experience band + count/sort row.
      this.renderMobileStrip(d),
      this.renderExpBand(d),
      h("div", { style: s("flex:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 12px;min-height:38px;border-bottom:1px solid var(--line)") },
        d.isList && h("span", { key: "rl", style: s("font-size:14px;font-weight:700;color:var(--ink)") }, d.resultLabelShort),
        h("button", { type: "button", onClick: this.openSheet("sort"), "aria-expanded": sheet === "sort", "aria-haspopup": "true", className: "hv-tx-accent", style: s("margin-left:auto;min-height:44px;display:flex;align-items:center;gap:5px;padding:0 6px;background:transparent;border:0;font-size:14px;font-weight:600;color:var(--ink);cursor:pointer") },
          raw(SORT_ICON), h("span", { style: s("white-space:nowrap") }, d.sortLabel), raw(CHEV_MUTED))),
      // Sort popover (sort stays in the count row, not the strip).
      h("div", { style: s("position:relative;height:0;z-index:6") },
        sheet === "sort" && h("div", { key: "ss" },
          h("div", { onClick: this.closeSheet, style: s("position:absolute;top:0;left:0;right:0;height:1200px;z-index:1;background:transparent") }),
          h("div", { "data-filter-sheet": "true", role: "dialog", "aria-label": "Sort", style: s("position:absolute;top:2px;right:16px;z-index:2;width:230px;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;box-shadow:0 10px 30px rgba(10,58,117,0.18);animation:sheetdown 160ms cubic-bezier(.22,.61,.36,1)") },
            h(FilterPanel, this.filterProps(d, { isSort: true }))))),
      // Content region. The open job overlays ONLY this region (the chrome above stays visible);
      // the full-page filter (below) overlays the WHOLE body region, replacing the chrome.
      h("div", { style: s("flex:1;min-height:0;position:relative") },
        h("div", { ref: this.setListEl, "data-list-scroller": "true", style: s("position:absolute;inset:0;overflow-y:auto;-webkit-overflow-scrolling:touch") }, this.listBody(d, false)),
        d.onPage && h("div", { key: "page", style: s("position:absolute;inset:0;z-index:1;overflow-y:auto;-webkit-overflow-scrolling:touch;background:var(--surface)") },
          h(JobPage, { page: d.page, categories: R.CATEGORIES, back: this.back, isMobilePage: true, isPanel: false }))),
      // Full-page filter — own header/scroll/sticky footer, covering strip+band+count+list.
      sheet === "all" && this.renderFilterPage(d)
    );
  }

  // Job-type multi-select for the alert form — same categories and checkbox format as the board's
  // Work Type filter, packaged as a dropdown (a trigger button that expands an inline checkbox
  // list). Optional: no selection = "all job types".
  alertCatSelect(){
    const picked = this.state.alertCats || [];
    const open = this.state.alertCatOpen;
    const allOn = picked.length === R.CATEGORIES.length;
    const summary = picked.length ? (picked.length > 2 ? picked.slice(0, 2).join(", ") + " +" + (picked.length - 2) : picked.join(", ")) : "All job types";
    const box = "box-sizing:border-box;width:100%;min-height:48px;padding:0 12px;display:flex;align-items:center;justify-content:space-between;gap:8px;border:1px solid var(--line);border-radius:3px;background:var(--surface);font-size:16px;color:var(--ink);cursor:pointer;text-align:left";
    const checkbox = (on) => h("span", { "aria-hidden": "true", style: s("flex:none;width:18px;height:18px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (on ? "var(--ink)" : "var(--line)") + ";background:" + (on ? "var(--ink)" : "var(--surface)")) }, on ? raw(CHECK14) : null);
    return h("div", { style: s("position:relative") },
      h("button", { type: "button", onClick: this.toggleAlertCatOpen, "aria-expanded": open, "aria-haspopup": "true", className: "fc-bd-ink", style: s(box + (picked.length ? ";font-weight:700" : ";color:var(--ink-muted)")) },
        h("span", { style: s("overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, summary), raw(open ? CHEV : CHEV_MUTED)),
      open && h("div", { role: "group", "aria-label": "Job type", style: s("margin-top:6px;border:1px solid var(--line);border-radius:3px;background:var(--surface);max-height:214px;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:6px") },
        h("button", { type: "button", role: "checkbox", "aria-checked": allOn, onClick: this.selectAllAlertCats, className: "hv-bg-sunk",
            style: s("width:100%;box-sizing:border-box;display:flex;align-items:center;gap:8px;min-height:36px;padding:0 5px;background:transparent;border:0;border-radius:3px;cursor:pointer;font-size:14px;font-weight:700;color:var(--ink);text-align:left") },
          checkbox(allOn), h("span", null, "All job types")),
        h("div", { style: s("display:grid;grid-template-columns:1fr 1fr;gap:1px 8px") },
          R.CATEGORIES.map((c, i) => { const on = picked.indexOf(c) >= 0; return h("button", { key: i, type: "button", role: "checkbox", "aria-checked": on, onClick: this.toggleAlertCat(c), className: "hv-bg-sunk",
              style: s("display:flex;align-items:center;gap:7px;min-height:38px;padding:0 4px;background:transparent;border:0;border-radius:3px;cursor:pointer;text-align:left") },
            checkbox(on),
            h("span", { style: s("flex:1;font-size:13px;font-weight:" + (on ? "700" : "500") + ";line-height:1.15;color:var(--ink)") }, c)); }))));
  }

  renderAlerts(){
    if (!this.state.alertsOpen) return null;
    const phase = this.state.alertPhase;
    const inputStyle = "box-sizing:border-box;width:100%;min-height:48px;padding:0 12px;border:1px solid var(--line);border-radius:3px;background:var(--surface);font-family:inherit;font-size:16px;color:var(--ink);outline:none";
    const field = (label, node) => h("label", { style: s("display:grid;gap:6px") },
      h("span", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, label), node);

    const body = phase === "creating"
      ? h("div", { key: "cr", style: s("display:grid;justify-items:center;gap:14px;padding:24px 0 28px") },
          h("span", { "aria-hidden": "true", style: s("width:34px;height:34px;border:3px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite") }),
          h("div", { role: "status", style: s("font-size:15px;font-weight:600;color:var(--ink)") }, "Creating alert…"))
      : phase === "done"
      ? h("div", { key: "dn", style: s("display:grid;justify-items:center;gap:14px;padding:4px 0 6px;text-align:center") },
          h("div", { className: "dsp", style: s("font-size:21px;line-height:1.16;font-weight:800;color:var(--ink)") }, "You’re on the list"),
          h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") }, "We’ll email new jobs as they’re posted."),
          h("img", { src: "/logo.png", alt: "", width: 56, height: 56, style: s("width:56px;height:56px;object-fit:contain") }))
      : h("div", { key: "fm", style: s("display:grid;gap:12px") },
          h("div", { style: s("display:grid;gap:5px;padding-right:40px") },
            h("div", { className: "dsp", style: s("font-size:21px;line-height:1.16;font-weight:800;color:var(--ink);text-wrap:pretty") }, "Get Job Alerts"),
            h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") }, "Get alerted when no-experience needed jobs get posted.")),
          field("Email", h("input", { type: "email", value: this.state.alertEmail, onChange: this.onAlertEmail, onKeyDown: this.onAlertKey, placeholder: "you@email.com", "aria-label": "Email address", className: "fc-bd-ink", style: s(inputStyle) })),
          field("ZIP code or city", h("input", { type: "text", value: this.state.alertZip, onChange: this.onAlertZip, onKeyDown: this.onAlertKey, placeholder: "e.g. 98101 or Seattle", "aria-label": "ZIP code or city", className: "fc-bd-ink", style: s(inputStyle) })),
          field("Job type", this.alertCatSelect()),
          this.state.alertError && h("div", { key: "er", role: "alert", style: s("font-size:14px;font-weight:600;color:var(--accent)") }, this.state.alertError),
          h("button", { key: "go", type: "button", onClick: this.submitAlerts, style: s("min-height:48px;border-radius:3px;background:var(--accent);border:0;font-size:15px;font-weight:800;letter-spacing:0.04em;text-transform:uppercase;color:var(--accent-ink);cursor:pointer") }, "Create alert"));

    return h("div", { style: s("position:fixed;inset:0;z-index:20;display:grid;place-items:center;padding:20px;background:rgba(10,58,117,0.42);animation:scrimin 160ms ease-out") },
      h("div", { onClick: this.closeAlerts, style: s("position:absolute;inset:0") }),
      h("div", { role: "dialog", "aria-modal": "true", "aria-label": "Get new jobs by email", style: s("position:relative;width:min(390px,100%);padding:20px;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;box-shadow:0 18px 44px rgba(10,58,117,0.24);display:grid;gap:12px") },
        h("button", { type: "button", onClick: this.closeAlerts, "aria-label": "Close", className: "hv-tx-ink", style: s("position:absolute;top:6px;right:6px;width:44px;height:44px;display:grid;place-items:center;background:transparent;border:0;cursor:pointer;color:var(--ink-muted);z-index:1") }, raw(CLOSE)),
        body
      )
    );
  }

  // Persistent job-alert bar — a navy strip pinned to the bottom of the 100vh board (flex:none,
  // stays put through scroll), on the browse board AND job pages, desktop and mobile. The alert CTA
  // was moved here from the header (alertsInHeader:false below), so the board has ONE alert entry
  // point, always in reach. Same marigold .alert-cta styling and openAlerts wiring as the header.
  renderAlertBar(){
    return h("footer", { style: s("flex:none;background:var(--ink);padding:7px 12px;display:flex;justify-content:center") },
      h("button", { type: "button", onClick: this.openAlerts, "aria-haspopup": "dialog", className: "alert-cta",
        style: s("min-height:44px;display:inline-flex;align-items:center;justify-content:center;padding:0 18px;border:0;border-radius:3px;font-size:13px;font-weight:700;letter-spacing:0.03em;text-transform:uppercase;color:var(--mark-ink);background:var(--mark);cursor:pointer") },
        "Get job alerts"));
  }

  render(){
    const d = this.derive();
    // Every page is the board — including a cold /jobs/{slug} arrival (job panel seeded, list
    // skeleton). There is no headless job document.
    return h("div", { className: "board-scope", style: s("height:100vh;display:flex;flex-direction:column;overflow:hidden;position:relative;background:var(--surface)") },
      h(Header, { productName: PRODUCT, onAlerts: this.openAlerts, wide: this.state.wide, alertsInHeader: false }),
      this.state.wide ? this.renderWide(d) : this.renderMobile(d),
      this.renderAlertBar(),
      this.renderAlerts()
    );
  }
}

// A standalone /jobs/{slug} page already bakes the job's full description (the data/describe.js
// output, serialized by the bake). jobs_detail's ONLY runtime contribution to what this page
// renders is description_html — every other field it shows (title, pay, experience, expired,
// apply) comes from jobs_list, which is fetched live at mount. So on standalone we render the
// baked description verbatim and skip the jobs_detail round trip entirely: no second fetch, and
// no blank window where React would show DESC_LOADING until that fetch returns. Captured before
// createRoot().render() replaces #root. (In-app opens keep the fetch — no baked description
// exists for an arbitrarily-opened job there.)
const BAKED_DESC = (() => { try { const el = document.querySelector('[data-desc-html]'); return el ? el.innerHTML : null; } catch (e) { return null; } })();

const mount = (props) => {
  const root = window.ReactDOM.createRoot(document.getElementById("root"));
  root.render(h(BoardApp, props));
};
// Seed handed over from the landing's "See jobs" / card tap (sessionStorage) — the jobs_list it
// already held. One-shot: read + clear, so a later reload of the board fetches fresh. Lets the
// board mount with data immediately: no ~0.9MB fetch on the critical path, and no stale
// baked-list→filtered-list flash when arriving with a search.
const readSeed = () => {
  try { const s = window.sessionStorage.getItem("npj_seed"); if (s) { window.sessionStorage.removeItem("npj_seed"); const a = JSON.parse(s); if (Array.isArray(a) && a.length) return a; } } catch (e) {}
  return null;
};
const seed = readSeed();

// A cold /jobs/ browse load bakes the FULL detail of the job the desktop board auto-opens
// (derive()'s pageRecs[0] — newest no-experience job) as id __npj_jobs_seed. Seeding
// state.details with it lets the panel paint its real description on the first frame, instead of
// a loading skeleton that swaps to the description once jobs_detail resolves — the swap is the
// ~0.12 desktop cold-load layout shift. Present only on /jobs/ (build.mjs); elsewhere it's a
// no-op (null). Keyed by internal_id, so it applies only if that job is the one that opens.
const readJobsSeed = () => {
  try { const el = document.getElementById("__npj_jobs_seed"); if (el) { const d = (JSON.parse(el.textContent) || {}).detail; if (d && d.internal_id) return { [d.internal_id]: d }; } } catch (e) {}
  return null;
};
const jobsSeedDetails = readJobsSeed();

// A /jobs/{slug} arrival is a JOB PAGE: seed the panel from the inlined record blob (id
// __npj_job — the job's jobs_list row, no description_html) and paint immediately — chrome +
// panel + list. Without a handed-over seed the list is a skeleton that hydrates from jobs_list
// in componentDidMount; WITH a seed it fills instantly. The panel's description comes from the
// baked DOM (BAKED_DESC), no jobs_detail round trip.
const isJobRoute = (() => { try { return RT.parsePath(window.location.pathname).kind === "job"; } catch (e) { return false; } })();
if (isJobRoute) {
  let openJob = null;
  try { const el = document.getElementById("__npj_job"); if (el) openJob = (JSON.parse(el.textContent) || {}).job || null; } catch (e) {}
  mount(seed ? { openJob: openJob, initialRecs: seed } : { openJob: openJob });
} else if (seed) {
  mount({ initialRecs: seed, initialDetails: jobsSeedDetails || undefined });   // handed the list — mount with data, no fetch, no flash
} else if (window.location.search.length > 1) {
  // A FILTERED arrival (any query — location/category/pay/sort/…) that the location-agnostic
  // baked page can't reflect. Mount a skeleton NOW and fetch jobs_list in componentDidMount,
  // rather than leaving the stale baked (unfiltered) list up for the length of the fetch.
  mount({});
} else {
  // Clean path (/washington/{cat}/ with no query): the baked list already matches the result,
  // so keep it on screen during the fetch (mount only once data is in hand) — no skeleton.
  SB.listJobs().then((recs) => mount({ initialRecs: recs, initialDetails: jobsSeedDetails || undefined })).catch(() => mount(null));
}
