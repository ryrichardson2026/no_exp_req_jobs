/* Landing page. One responsive layout: the wide and narrow designs from the old
   Landing Screen are chosen at render time from a matchMedia breakpoint (not two
   frames), so exactly one is in the DOM and the page reflows on resize. All record and
   location logic comes from the shared modules — no inline copies. */
import { h, s, raw } from "./ui/h.js";
import { Header } from "./ui/header.js";
import { JobCard } from "./ui/jobCard.js";
import { Pressable } from "./ui/pressable.js";
import { catIconSvg } from "./ui/catIcons.js";
import * as R from "./data/record.js";
import * as L from "./data/resolve.js";
import * as SB from "./data/supabase.js";
import * as RT from "./data/routes.js";

const React = window.React;
const BP = "(min-width:768px)";
const PRODUCT = "NoProbJobs.com";

const STAR = (px) => '<svg viewBox="0 0 200 200" width="' + px + '" height="' + px + '" aria-hidden="true" style="display:block"><polygon points="100.0,3.0 126.8,35.3 168.6,31.4 164.7,73.2 197.0,100.0 164.7,126.8 168.6,168.6 126.8,164.7 100.0,197.0 73.2,164.7 31.4,168.6 35.3,126.8 3.0,100.0 35.3,73.2 31.4,31.4 73.2,35.3" fill="var(--mark)" stroke="var(--ink)" stroke-width="5" stroke-linejoin="miter"></polygon></svg>';
const SEARCH_ICON = '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="7.6" cy="7.6" r="5.4"></circle><path d="M11.6 11.6l4.2 4.2"></path></svg>';
const CHEV = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="currentColor" stroke-width="1.6" style="flex:none" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const CHEV_MUTED = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="var(--ink-muted)" stroke-width="1.6" style="flex:none" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const ROW_CHECK = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="var(--accent-ink)" stroke-width="2.2" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';
const VP_CHECK = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--mark-ink)" stroke-width="1.9"><circle cx="8" cy="8" r="6.6"></circle><path d="M5 8.3l2.1 2.1L11 6.1"></path></svg>';
const TICK = '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="2.4" style="flex:none" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';
const CLOSE = '<svg width="13" height="13" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1.6 1.6l11.8 11.8"></path><path d="M13.4 1.6L1.6 13.4"></path></svg>';
// Pixel-art thumbs up for the signup confirmation — blocky orthogonal outline, marigold
// fill + ink outline (matches the hero star), with folded-finger lines on the fist.
const THUMB_UP = '<svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true" style="display:block"><path d="M17 4 H29 V22 H52 V52 H10 V22 H17 Z" fill="var(--mark)" stroke="var(--ink)" stroke-width="3.5" stroke-linejoin="miter"></path><path d="M22 30 H46 M22 38 H46 M22 46 H41" stroke="var(--ink)" stroke-width="2.5" fill="none"></path></svg>';

class LandingApp extends React.Component {
  constructor(props){
    super(props);
    this.state = {
      recs: props.initialRecs || null, cities: [], zips: {},
      cats: [], locDraft: "", radius: 15, catOpen: false,
      fbOpen: false, fbName: "", fbEmail: "", fbText: "",
      alertOpen: false, alertEmail: "", alertLoc: "", alertCats: [], alertCatOpen: false,
      alertPhase: "form", alertError: "", toast: "", logoOk: {},
      wide: window.matchMedia(BP).matches,
    };
  }

  static CAP_PER_EMPLOYER = 2;
  capByEmployer(list, want){
    const seen = {}, out = [];
    for (let i = 0; i < list.length && out.length < want; i++) {
      const co = list[i].company_name || "";
      if ((seen[co] || 0) >= LandingApp.CAP_PER_EMPLOYER) continue;
      seen[co] = (seen[co] || 0) + 1;
      out.push(list[i]);
    }
    return out;
  }

  static FRESH_WINDOW_DAYS = 7;
  static FRESH_FLOOR = 5;
  freshCount(recs){
    const now = R.today().getTime();
    const span = LandingApp.FRESH_WINDOW_DAYS * 86400000;
    return recs.filter((r) => {
      const t = R.parseDate(r.posted_at);
      return t !== null && t <= now && now - t <= span;
    }).length;
  }

  componentDidMount(){
    window.addEventListener("mousedown", this.onDocDown, true);
    window.addEventListener("keydown", this.onKeyDown);
    this._mql = window.matchMedia(BP);
    this._onMql = () => this.setState({ wide: this._mql.matches });
    this._mql.addEventListener("change", this._onMql);
    SB.pulledAt().then((d) => R.setToday(d)).catch(() => {});
    if (this.state.recs) {
      this.preflightLogos(this.state.recs);                 // seeded at mount — no refetch, no wipe
    } else {
      SB.listJobs().then((recs) => {
        this.setState({ recs });
        this.preflightLogos(recs);
      }).catch((e) => { console.error("jobs_list failed to load", e); this.setState({ recs: [] }); });
    }
    import("./data/cities.js").then((m) => this.setState({ cities: m.CITIES }))
      .catch((e) => console.error("cities.js failed to load", e));
    import("./data/zips.js").then((m) => this.setState({ zips: m.ZIPS }))
      .catch((e) => console.error("zips.js failed to load", e));
  }

  componentWillUnmount(){
    window.removeEventListener("mousedown", this.onDocDown, true);
    window.removeEventListener("keydown", this.onKeyDown);
    if (this._mql) this._mql.removeEventListener("change", this._onMql);
    clearTimeout(this._t);
  }

  onDocDown = (e) => {
    if (!this.state.catOpen) return;
    const t = e.target;
    if (t && t.closest && (t.closest("[data-filter-pop]") || t.closest("[data-filter-trigger]"))) return;
    this.setState({ catOpen: false });
  };
  onKeyDown = (e) => {
    if (e.key !== "Escape") return;
    if (this.state.alertOpen) { e.preventDefault(); this.closeAlerts(); return; }
    if (this.state.fbOpen) { e.preventDefault(); this.setState({ fbOpen: false }); return; }
    if (this.state.catOpen) { e.preventDefault(); this.setState({ catOpen: false }); }
  };

  alertsDone(){
    try { if (localStorage.getItem("npj.alerts") === "done") return true; } catch (e) {}
    return LandingApp._alertsDone === true;
  }
  markAlertsDone(){
    LandingApp._alertsDone = true;
    try { localStorage.setItem("npj.alerts", "done"); } catch (e) {}
  }
  _payTop(){
    const rates = (this.state.recs || [])
      .filter((r) => r.salary_is_stated && r.pay_period === "HOURLY")
      .map((r) => r.salary_max || r.salary_min).filter((v) => v > 0)
      .sort((a, b) => a - b);
    if (rates.length < 4) return null;
    return Math.ceil(rates[Math.floor(0.75 * (rates.length - 1))]);
  }
  _topCats(){
    if (this.state.recs === null) return [];
    return R.CATEGORIES.map((c) => {
      const n = (this.state.recs || []).filter((r) => R.recordCats(r).indexOf(c) >= 0).length;
      return { label: c, n: n, count: n + (n === 1 ? " job" : " jobs"), hasCount: n > 0,
               href: this.boardHref({ category: c, loc: "" }) };
    }).sort((a, b) => b.n - a.n);   // C4: all nine show (no "+4 more"); ordered by volume
  }

  // Open with the current filters pre-filled — someone browsing Retail in Seattle who
  // opens alerts shouldn't re-enter it. Resets to the form phase each open.
  openAlerts = () => this.setState({ alertOpen: true, catOpen: false, fbOpen: false, alertPhase: "form",
    alertError: "", alertCatOpen: false, alertCats: this.state.cats.slice(), alertLoc: this.state.locDraft });
  closeAlerts = () => { this.markAlertsDone(); clearTimeout(this._alertT); this.setState({ alertOpen: false }); };
  onAlertEmail = (e) => this.setState({ alertEmail: e.target.value });
  onAlertLoc = (e) => this.setState({ alertLoc: e.target.value });
  onAlertKey = (e) => { if (e.key === "Enter") { e.preventDefault(); this.sendAlerts(); } };
  toggleAlertCatOpen = () => this.setState((st) => ({ alertCatOpen: !st.alertCatOpen }));
  toggleAlertCat = (c) => () => this.setState((st) => ({ alertCats: st.alertCats.indexOf(c) >= 0 ? st.alertCats.filter((v) => v !== c) : st.alertCats.concat([c]) }));
  // "Apply all" is a select-all checkbox, not a commit button: checks every option, or
  // clears them if all are already on. The menu stays live.
  alertApplyAll = () => this.setState((st) => ({ alertCats: st.alertCats.length === R.CATEGORIES.length ? [] : R.CATEGORIES.slice() }));
  sendAlerts = () => {
    const email = (this.state.alertEmail || "").trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { this.setState({ alertPhase: "form", alertError: "Enter a valid email address." }); return; }
    this.setState({ alertPhase: "creating", alertError: "" });
    const wait = new Promise((r) => { this._alertT = setTimeout(r, 2500); });   // deliberate 2.5s "Creating alert" loader
    Promise.all([SB.captureAlert({ email, categories: this.state.alertCats, location: this.state.alertLoc, source: "landing" }), wait])
      .then(() => { this.markAlertsDone(); this.setState({ alertPhase: "done" }); })
      .catch(() => this.setState({ alertPhase: "form", alertError: "Couldn’t save that — please try again." }));
  };

  openFeedback = () => this.setState({ fbOpen: true, catOpen: false });
  closeFeedback = () => this.setState({ fbOpen: false });
  onFbName = (e) => this.setState({ fbName: e.target.value });
  onFbEmail = (e) => this.setState({ fbEmail: e.target.value });
  onFbText = (e) => this.setState({ fbText: e.target.value });
  sendFeedback = () => {
    this.setState({ fbOpen: false, fbName: "", fbEmail: "", fbText: "", toast: "Thanks — that’s logged." });
    clearTimeout(this._t);
    this._t = setTimeout(() => this.setState({ toast: "" }), 2600);
  };

  preflightLogos(recs){
    const seen = {};
    recs.forEach((r) => {
      const d = r.employer_domain;
      if (!d || seen[d] || !R.ownsDomain(r.company_name, d)) return;
      seen[d] = true;
      const img = new Image();
      img.onerror = () => {};
      img.onload = () => {
        if (img.naturalWidth < 16) return;
        this.setState((st) => { const ok = Object.assign({}, st.logoOk); ok[d] = true; return { logoOk: ok }; });
      };
      img.src = R.logoUrl(d);
    });
  }

  openCat = () => this.setState((st) => ({ catOpen: !st.catOpen }));
  // Category chips are browsing, not alert intent (weight: none) — selecting them no
  // longer opens the alert modal. Signup volume is the launch signal, so it must measure
  // a stated interest in being notified about jobs, not exploratory filtering. The alert
  // modal now fires only where genuine intent lives: on the board, after job views (a
  // completed search with a location seeds it there). The landing keeps the explicit
  // "Get job alerts" button.
  toggleCat = (c) => () => this.setState((st) => ({ cats: st.cats.indexOf(c) >= 0 ? st.cats.filter((v) => v !== c) : st.cats.concat([c]) }));
  selectAllCats = () => this.setState((st) => ({ cats: st.cats.length === R.CATEGORIES.length ? [] : R.CATEGORIES.slice() }));   // "Apply all" select-all, live
  onLocDraft = (e) => this.setState({ locDraft: e.target.value });
  onSubmitKey = (e) => { if (e.key === "Enter") { e.preventDefault(); this.submit(); } };
  setRadius = (r) => () => this.setState({ radius: r });

  boardHref(over){
    const o = over || {};
    const loc = o.loc !== undefined ? o.loc : this.state.locDraft;
    const cats = o.category ? [o.category] : this.state.cats;
    // Landing has no per-record state context, so it uses the launch-market parameter
    // (RT.MARKET) for the browse path — one explicit value, not an inventory scan.
    const single = cats.length === 1 ? cats[0] : null;
    const path = RT.browsePath(RT.MARKET, single);        // /washington/ or /washington/{cat}/
    const q = [];
    if (cats.length > 1) q.push("category=" + cats.map(encodeURIComponent).join(","));
    if (loc) {
      q.push("location=" + encodeURIComponent(loc));
      if (/^\d{5}$/.test(String(loc).trim())) q.push("radius=" + this.state.radius);
    }
    return path + (q.length ? "?" + q.join("&") : "");
  }
  submit = () => { window.location.href = this.boardHref(); };

  shape(r){
    const domain = r.employer_domain || "";
    const showLogo = R.ownsDomain(r.company_name, domain) && !!this.state.logoOk[domain];
    // The crawlable href stays the flat job permalink (SEO internal link + right-click-open);
    // a click, though, drops the visitor INTO the board filtered to the job's category with
    // its detail open — the browsing experience, not the isolated reading page. Falls back to
    // the permalink if we can't form a board URL (no category or no job_number).
    const primaryCat = R.recordCats(r)[0];
    const boardJobHref = (primaryCat && r.job_number != null)
      ? RT.browsePath(r.state, primaryCat) + "?job=" + r.job_number
      : RT.jobPath(r) + "/";
    const go = () => { window.location.href = boardJobHref; };
    return Object.assign({}, r, {
      id: r.internal_id,
      company: r.company_name.split(" /")[0],
      cardTitle: R.cardTitle(r.title),
      logoImg: showLogo ? R.logoImg(R.logoUrl(domain), 20) : null,
      showLogo, showMonogram: !showLogo,
      monogram: (r.company_name || "?").trim().charAt(0).toUpperCase(),
      locationLine: [L.cityName(r.city), r.state].filter(Boolean).join(", "),
      pay: R.money(r), posted: R.postedLabel(r.posted_at),
      expLabel: R.EXP_LABEL[r.experience_condition] || null,
      expStrong: r.experience_condition === "NONE_NEEDED" || r.experience_condition === "WAIVED",
      expSoft: r.experience_condition === "PREFERRED",
      href: RT.jobPath(r) + "/",              // crawlable permalink; the click is intercepted below
      onCardClick: (e) => { if (e && e.preventDefault) e.preventDefault(); go(); },
      isSelected: false, open: go,
      openKey: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } },
    });
  }

  // ── hero ──────────────────────────────────────────────────
  burst(){
    const payTop = this._payTop();
    if (!payTop) return null;
    const label = "Most jobs pay up to $" + payTop + " an hour";
    // One DOM; size/position/font come from CSS (.hero-burst*) per the viewer's width. The
    // star SVG is rendered at 112 and scaled to fit the container via `.hero-burst svg`.
    return h("div", { className: "hero-burst", role: "img", "aria-label": label },
      raw(STAR(112)),
      h("div", { className: "hero-burst-txt" },
        h("span", { className: "hero-burst-cap" }, "Up to"),
        h("span", { className: "hero-burst-amt" }, "$" + payTop),
        h("span", { className: "hero-burst-cap" }, "an hour")
      )
    );
  }
  renderHero(){
    // One DOM for both widths; CSS (.hero*) handles the mobile/desktop differences so the
    // prerendered mobile markup doesn't jump to the desktop hero on mount. (see styles.css)
    return h("div", { className: "hero" },
      this.burst(),
      h("h1", { className: "hero-h1" }, "Companies hiring now."),
      h("div", { className: "hero-badge" }, "No experience needed")
    );
  }

  // ── category selector (search card) ───────────────────────
  catOptions(){
    const picked = this.state.cats;
    return R.CATEGORIES.map((c) => ({          // static list — never gated on recs, so the chips are stable from first paint
      label: c, isOn: picked.indexOf(c) >= 0, isOff: picked.indexOf(c) < 0, pick: this.toggleCat(c),
    }));
  }
  renderCatWide(){
    const allOn = this.state.cats.length === R.CATEGORIES.length;
    return h("div", { role: "group", "aria-label": "Type of work", style: s("display:flex;flex-wrap:wrap;justify-content:center;gap:8px") },
      h("button", { key: "all", type: "button", onClick: this.selectAllCats, "aria-pressed": allOn, className: allOn ? undefined : "hv-bg-fact",
          style: s("min-height:46px;display:inline-flex;align-items:center;padding:0 15px;border:1px solid var(--ink);border-radius:3px;background:" + (allOn ? "var(--ink)" : "var(--surface-raised)") + ";font-size:15px;font-weight:700;color:" + (allOn ? "var(--surface)" : "var(--ink)") + ";cursor:pointer;white-space:nowrap") }, "Apply all"),
      this.catOptions().map((c, i) => c.isOn
        ? h("button", { key: i, type: "button", onClick: c.pick, "aria-pressed": true, style: s("min-height:46px;display:inline-flex;align-items:center;gap:7px;padding:0 15px;border:1px solid var(--ink);border-radius:3px;background:var(--ink);font-size:15px;font-weight:700;color:var(--surface);cursor:pointer;white-space:nowrap") }, raw(catIconSvg(c.label, 20, "currentColor")), h("span", null, c.label))
        : h("button", { key: i, type: "button", onClick: c.pick, "aria-pressed": false, className: "hv-bg-fact", style: s("min-height:46px;display:inline-flex;align-items:center;gap:7px;padding:0 15px;border:1px solid var(--ink);border-radius:3px;background:var(--surface-raised);font-size:15px;font-weight:600;color:var(--ink);cursor:pointer;white-space:nowrap") }, raw(catIconSvg(c.label, 20)), h("span", null, c.label)))
    );
  }
  renderCatMobile(){
    const picked = this.state.cats;
    const allOn = picked.length === R.CATEGORIES.length;
    const listOf = (arr) => (arr.length > 2 ? arr.slice(0, 2).join(", ") + " +" + (arr.length - 2) : arr.join(", "));
    const catLabel = picked.length ? listOf(picked) : null;
    return h("div", { style: s("position:relative") },
      picked.length
        ? h("button", { type: "button", "data-filter-trigger": "true", onClick: this.openCat, "aria-expanded": this.state.catOpen, "aria-haspopup": "true", style: s("width:100%;box-sizing:border-box;min-height:48px;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 12px;border:2px solid var(--ink);border-radius:3px;background:var(--fact);font-size:15px;font-weight:700;color:var(--ink);cursor:pointer;text-align:left") },
            h("span", { style: s("overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, catLabel), raw(CHEV))
        : h("button", { type: "button", "data-filter-trigger": "true", onClick: this.openCat, "aria-expanded": this.state.catOpen, "aria-haspopup": "true", className: "hv-bg-fact", style: s("width:100%;box-sizing:border-box;min-height:48px;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 12px;border:2px solid var(--ink);border-radius:3px;background:var(--surface-raised);font-size:15px;font-weight:600;color:var(--ink);cursor:pointer;text-align:left") },
            h("span", { style: s("white-space:nowrap") }, "Type of work"), raw(CHEV_MUTED)),
      this.state.catOpen && h("div", { key: "pop", "data-filter-pop": "true", role: "dialog", "aria-label": "Type of work", style: s("position:absolute;top:54px;left:0;z-index:6;width:330px;max-width:100%;box-sizing:border-box;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;box-shadow:0 10px 24px rgba(10,58,117,0.18);animation:sheetdown 160ms cubic-bezier(.22,.61,.36,1)") },
        h("div", { style: s("padding:8px 0") },
          h("div", { style: s("padding:6px 14px 8px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink)") }, "Type of work"),
          h("button", { key: "all", type: "button", role: "checkbox", "aria-checked": allOn, onClick: this.selectAllCats, className: "hv-bg-sunk", style: s("width:100%;box-sizing:border-box;min-height:44px;display:flex;align-items:center;gap:10px;padding:0 14px;border:0;background:transparent;font-size:15px;font-weight:700;color:var(--ink);text-align:left;cursor:pointer") },
            allOn ? h("span", { style: s("flex:none;width:18px;height:18px;border-radius:3px;background:var(--ink);display:grid;place-items:center") }, raw(ROW_CHECK)) : h("span", { style: s("flex:none;width:18px;height:18px;border-radius:3px;border:1px solid var(--ink);background:var(--surface-raised)") }),
            h("span", null, "Apply all")),
          this.catOptions().map((c, i) => h("button", { key: i, type: "button", onClick: c.pick, "aria-pressed": c.isOn, className: "hv-bg-sunk", style: s("width:100%;box-sizing:border-box;min-height:44px;display:flex;align-items:center;gap:10px;padding:0 14px;border:0;background:transparent;font-size:15px;color:var(--ink);text-align:left;cursor:pointer") },
            c.isOn
              ? h("span", { style: s("flex:none;width:18px;height:18px;border-radius:3px;background:var(--ink);display:grid;place-items:center") }, raw(ROW_CHECK))
              : h("span", { style: s("flex:none;width:18px;height:18px;border-radius:3px;border:1px solid var(--ink);background:var(--surface-raised)") }),
            raw(catIconSvg(c.label, 18)),
            h("span", null, c.label))),
          h("div", { style: s("display:flex;justify-content:flex-end;padding:8px 10px 2px;border-top:1px solid var(--line);margin-top:6px") },
            h("button", { type: "button", onClick: this.openCat, style: s("min-height:36px;padding:0 16px;border:0;border-radius:3px;background:var(--accent);font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:0.03em;color:var(--accent-ink);cursor:pointer") }, "Apply"))
        )
      )
    );
  }

  renderSearchCard(res, unmatched){
    const wide = this.state.wide;
    const isZipDraft = /^\d{5}$/.test(String(this.state.locDraft).trim());
    const radiusOptions = L.RADII.map((r) => ({ label: r + " mi", value: r, isOnCurrent: r === this.state.radius, isOnOther: r !== this.state.radius, pick: this.setRadius(r) }));
    return h("div", { style: s("width:100%;box-sizing:border-box;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;padding:12px;display:grid;gap:10px") },
      // Both layouts in the DOM; CSS (.cat-wide/.cat-narrow) shows the one that fits the
      // viewer's width, so the prerendered mobile markup doesn't jump to the chip row on mount.
      h("div", { key: "cw", className: "cat-wide" }, this.renderCatWide()),
      h("div", { key: "cn", className: "cat-narrow" }, this.renderCatMobile()),
      // location row
      h("div", { style: s("width:100%;max-width:520px;margin:0 auto;display:flex;gap:8px;align-items:stretch") },
        h("div", { className: "fw-bd-accent", style: s("flex:1;min-width:0;display:flex;align-items:stretch;border:2px solid var(--ink);border-radius:3px;background:var(--surface-raised);overflow:hidden") },
          h("input", { type: "text", value: this.state.locDraft, onChange: this.onLocDraft, onKeyDown: this.onSubmitKey, placeholder: "City, state, or ZIP", "aria-label": "City, state, or ZIP", style: s("flex:1;min-width:0;box-sizing:border-box;min-height:48px;padding:0 12px;border:0;background:transparent;font-size:16px;color:var(--ink);outline:0") }),
          h("button", { type: "button", onClick: this.submit, "aria-label": "See jobs", style: s("flex:none;min-height:48px;display:flex;align-items:center;justify-content:center;gap:8px;padding:0 18px;border:0;background:var(--accent);color:var(--accent-ink);font-size:15px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;cursor:pointer") },
            raw(SEARCH_ICON), h("span", { key: "t", className: "see-jobs-txt" }, "See jobs"))
        )
      ),
      isZipDraft && h("div", { key: "rad", style: s("display:grid;gap:6px") },
        h("div", { style: s("display:flex;gap:8px;max-width:420px") },
          radiusOptions.map((r, i) => r.isOnCurrent
            ? h("button", { key: i, type: "button", onClick: r.pick, "aria-pressed": true, style: s("min-height:44px;flex:1;white-space:nowrap;border-radius:3px;font-size:14px;font-weight:700;cursor:pointer;background:var(--ink);border:1px solid var(--ink);color:var(--surface)") }, r.label)
            : h("button", { key: i, type: "button", onClick: r.pick, "aria-pressed": false, className: "hv-bg-fact", style: s("min-height:44px;flex:1;white-space:nowrap;border-radius:3px;font-size:14px;font-weight:600;cursor:pointer;background:var(--surface-raised);border:1px solid var(--ink);color:var(--ink)") }, r.label))),
        h("div", { style: s("font-size:12.5px;line-height:1.4;color:var(--ink-muted)") }, "Radius applies to a ZIP code. A city or state name filters to that area.")
      ),
      // help lines
      h("div", { className: "search-help", style: s("font-size:15px;line-height:1.35;color:var(--ink-muted);text-wrap:pretty") }, "Full-time, part-time, and overnight jobs"),
      h("div", { className: "search-ticks", style: s("display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;color:var(--ink)") },
        h("span", { style: s("display:inline-flex;align-items:center;gap:5px") }, raw(TICK), "Free to use"),
        h("span", { style: s("display:inline-flex;align-items:center;gap:5px") }, raw(TICK), "No resume required")
      ),
      unmatched && h("div", { key: "um", style: s("font-size:15px;line-height:1.5;color:var(--ink);text-wrap:pretty") }, L.unmatchedLine(res, this.state.locDraft) + " " + L.UNMATCHED_FIX)
    );
  }

  // ── value props ───────────────────────────────────────────
  vpItem(title, body){
    return { title, body };
  }
  renderValueProps(){
    // C3: now that this section follows the jobs, the first card is the curation
    // claim — states the work happened without explaining the process. "100% free"
    // is still stated on the search card ("Free to use") and the closing CTA.
    const items = [
      ["Checked first", "Every job is read against the employer’s requirements before it’s listed."],
      ["Posted this week", "Job listings updated daily."],
      ["Real employers", "Apply directly with the employer."],
      ["Requirements up front", "Less time spent on the wrong jobs."],
    ];
    if (this.state.wide) return h("section", { style: s("margin:0 -14px;padding:16px 14px;background:var(--ink);display:grid;gap:10px") },
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:16px;letter-spacing:0.04em;text-transform:uppercase;color:var(--mark)") }, "What’s different"),
      h("div", { style: s("display:grid;grid-template-columns:repeat(4,1fr);gap:8px") },
        items.map(([t, b], i) => h("div", { key: i, style: s("display:grid;align-content:start;gap:6px;padding:12px;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px") },
          h("span", { "aria-hidden": "true", style: s("width:32px;height:32px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(VP_CHECK)),
          h("span", { style: s("font-size:16px;font-weight:700;line-height:1.2;color:var(--ink)") }, t),
          h("span", { style: s("font-size:15px;line-height:1.35;color:var(--ink-muted);text-wrap:pretty") }, b))))
    );
    return h("section", { style: s("margin:0 -14px;padding:16px 14px;background:var(--ink);display:grid;gap:14px") },
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:16px;letter-spacing:0.04em;text-transform:uppercase;color:var(--mark)") }, "What’s different"),
      h("div", { style: s("display:grid;grid-template-columns:repeat(auto-fit,minmax(min(400px,100%),1fr));gap:10px 20px") },
        items.map(([t, b], i) => h("div", { key: i, style: s("display:flex;gap:10px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;width:32px;height:32px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(VP_CHECK)),
          h("div", { style: s("display:grid;gap:3px;min-width:0") },
            h("div", { style: s("font-size:16px;font-weight:700;color:var(--surface)") }, t),
            h("div", { style: s("font-size:15px;line-height:1.35;color:var(--line);text-wrap:pretty") }, b)))))
    );
  }

  renderBrowse(){
    const cards = this._topCats();
    const cols = this.state.wide ? "repeat(3,1fr)" : "1fr 1fr";
    return h("section", { style: s("display:grid;gap:var(--gap-block)") },
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:16px;letter-spacing:0.04em;text-transform:uppercase;color:var(--ink)") }, "Browse by type of work"),
      h("div", { style: s("display:grid;grid-template-columns:" + cols + ";grid-auto-rows:1fr;gap:12px") },
        cards.map((c, i) => h("div", { key: i, style: s("position:relative") },
          // stacked paper: a marigold sheet offset behind the white tile, both bordered.
          h("span", { "aria-hidden": "true", style: s("position:absolute;inset:0;transform:translate(4px,4px);background:var(--mark);border:2px solid var(--ink);border-radius:3px") }),
          h(Pressable, { tag: "a", href: c.href, className: "hv-bg-fact",
              styleFor: (pd) => s("position:relative;height:100%;box-sizing:border-box;display:grid;align-content:start;gap:7px;min-height:66px;padding:14px;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;text-decoration:none;transition:transform 45ms ease-out;" + (pd ? "transform:translate(4px,4px)" : "")) },
            raw(catIconSvg(c.label, 24)),
            h("div", { style: s("display:grid;gap:2px") },
              h("span", { style: s("font-family:var(--font-display);font-weight:800;font-size:16px;line-height:1.2;color:var(--ink)") }, c.label),
              c.hasCount && h("span", { key: "n", style: s("font-size:13px;line-height:1.35;font-weight:700;color:var(--accent)") }, c.count)))))),
      h("a", { href: this.boardHref(), style: s("justify-self:start;min-height:44px;display:inline-flex;align-items:center;font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.03em;color:var(--accent)") }, "See all types of work")
    );
  }

  renderRecent(){
    const loading = this.state.recs === null;
    let jobs = [];
    if (!loading) {
      const list = (this.state.recs || []).filter((r) => R.recordCats(r).length > 0).slice().sort(R.newestFirst);
      const want = this.state.wide ? 9 : 6;
      jobs = this.capByEmployer(list, want).map((r) => this.shape(r));
    }
    return h("section", { style: s("display:grid;gap:var(--gap-block)") },
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:16px;letter-spacing:0.04em;text-transform:uppercase;color:var(--ink)") }, "Recent jobs"),
      loading
        ? h("div", { style: s("display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:12px") },
            [1,2,3,4,5,6,7,8,9].map((k) => h("div", { key: k, style: s("background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;box-shadow:4px 4px 0 0 var(--ink);padding:12px;display:grid;gap:7px;align-content:start;animation:sk 1.4s ease-in-out infinite") },
              h("div", { style: s("height:11px;width:26%;background:var(--surface-sunk);border-radius:2px") }),
              h("div", { style: s("height:18px;width:64%;background:var(--surface-sunk);border-radius:2px") }),
              h("div", { style: s("height:13px;width:38%;background:var(--surface-sunk);border-radius:2px") }),
              h("div", { style: s("height:13px;width:30%;background:var(--surface-sunk);border-radius:2px") }))))
        : h("div", { role: "list", style: s("display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:12px") },
            jobs.map((job) => h(Pressable, { key: job.id, tag: "div",
                styleFor: (pd) => s("display:flex;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;transition:transform 45ms ease-out,box-shadow 45ms ease-out;"
                  + (pd ? "transform:translate(4px,4px);box-shadow:0 0 0 0 var(--ink)" : "box-shadow:4px 4px 0 0 var(--ink)")) },
              h("div", { style: s("flex:1;min-width:0") }, h(JobCard, { job, flush: true })))))
    );
  }

  renderClosing(){
    return h("section", { style: s("margin:0 -14px;padding:16px 14px;background:var(--mark);display:grid;gap:10px;justify-items:center") },
      h(Pressable, { tag: "a", href: this.boardHref(), className: "hv-underline-none",
          styleFor: (pd) => s("min-height:48px;display:inline-flex;align-items:center;padding:0 24px;border:0;background:var(--accent);font-size:16px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--accent-ink);text-decoration:none;white-space:nowrap;transition:box-shadow 40ms ease-out,transform 40ms ease-out;box-shadow:"
            + (pd ? "inset -3px -3px 0 0 var(--accent-lite),inset 3px 3px 0 0 var(--accent-dark);transform:translate(1px,1px)"
                  : "inset 3px 3px 0 0 var(--accent-lite),inset -3px -3px 0 0 var(--accent-dark)")) }, "Browse all jobs"),
      h("div", { style: s("font-size:15px;line-height:1.35;font-weight:600;color:var(--mark-ink);text-align:center") }, "Free for job seekers. No signup required.")
    );
  }

  renderFooter(){
    return h("footer", { style: s("flex:none;background:var(--ink)") },
      h("div", { style: s("max-width:1120px;margin:0 auto;padding:12px 14px;display:grid;justify-items:center;gap:2px") },
        h("button", { type: "button", onClick: this.openFeedback, "aria-haspopup": "dialog", "aria-expanded": this.state.fbOpen, className: "hv-bg-white10", style: s("min-height:36px;display:inline-flex;align-items:center;padding:0 16px;border:0;border-radius:3px;background:transparent;font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:0.03em;color:var(--mark);cursor:pointer") }, "Tell us what’s missing"),
        h("div", { style: s("display:flex;flex-wrap:wrap;justify-content:center;gap:8px 20px") },
          h("a", { href: "#terms", style: s("min-height:44px;display:inline-flex;align-items:center;font-size:13px;font-weight:500;color:var(--line)") }, "Terms"),
          h("a", { href: "#privacy", style: s("min-height:44px;display:inline-flex;align-items:center;font-size:13px;font-weight:500;color:var(--line)") }, "Privacy"),
          h("a", { href: "#accessibility", style: s("min-height:44px;display:inline-flex;align-items:center;font-size:13px;font-weight:500;color:var(--line)") }, "Accessibility"))
      )
    );
  }

  renderFeedback(){
    if (!this.state.fbOpen) return null;
    return h("div", { style: s("position:absolute;inset:0;z-index:8") },
      h("div", { onClick: this.closeFeedback, style: s("position:absolute;inset:0;background:rgba(10,58,117,0.42);animation:scrimin 180ms ease-out") }),
      h("div", { role: "dialog", "aria-modal": "true", "aria-label": "Tell us what’s missing", style: s("position:sticky;top:64px;z-index:1;width:390px;max-width:calc(100% - 32px);margin:0 auto;box-sizing:border-box;background:var(--surface);border:2px solid var(--ink);border-radius:3px;box-shadow:0 14px 30px rgba(10,58,117,0.22);display:grid;gap:12px;padding:16px;animation:sheetup 220ms cubic-bezier(.22,.61,.36,1)") },
        h("div", { style: s("display:flex;align-items:flex-start;justify-content:space-between;gap:8px") },
          h("div", { style: s("font-size:16px;font-weight:800;color:var(--ink)") }, "Tell us what’s missing"),
          h("button", { type: "button", onClick: this.closeFeedback, "aria-label": "Close", className: "hv-bg-sunk-tx-ink", style: s("flex:none;width:44px;height:44px;margin:-10px -10px 0 0;display:grid;place-items:center;background:transparent;border:0;border-radius:8px;cursor:pointer;color:var(--ink-muted)") }, raw(CLOSE))),
        h("label", { style: s("display:grid;gap:6px") },
          h("span", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Name"),
          h("input", { type: "text", value: this.state.fbName, onChange: this.onFbName, className: "fc-bd-accent", style: s("box-sizing:border-box;min-height:48px;padding:0 12px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:16px;color:var(--ink)") })),
        h("label", { style: s("display:grid;gap:6px") },
          h("span", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Email — optional"),
          h("input", { type: "email", value: this.state.fbEmail, onChange: this.onFbEmail, className: "fc-bd-accent", style: s("box-sizing:border-box;min-height:48px;padding:0 12px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:16px;color:var(--ink)") })),
        h("label", { style: s("display:grid;gap:6px") },
          h("span", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "What would you change?"),
          h("textarea", { value: this.state.fbText, onChange: this.onFbText, placeholder: "I wish I could filter by…", rows: 4, className: "fc-bd-accent", style: s("box-sizing:border-box;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--surface);font-family:inherit;font-size:16px;line-height:1.5;color:var(--ink);resize:vertical") })),
        h("button", { type: "button", onClick: this.sendFeedback, style: s("min-height:48px;border-radius:3px;background:var(--accent);border:0;font-size:16px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--accent-ink);cursor:pointer") }, "Send")
      )
    );
  }

  renderAlerts(){
    if (!this.state.alertOpen) return null;
    const phase = this.state.alertPhase;
    const cats = this.state.alertCats, allOn = cats.length === R.CATEGORIES.length;
    const jobLabel = !cats.length ? "Any type of work" : allOn ? "All types of work"
      : cats.length > 2 ? cats.slice(0, 2).join(", ") + " +" + (cats.length - 2) : cats.join(", ");
    const inputStyle = "box-sizing:border-box;width:100%;min-height:48px;padding:0 12px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:16px;color:var(--ink)";
    const rowStyle = "width:100%;box-sizing:border-box;min-height:44px;display:flex;align-items:center;gap:10px;padding:0 12px;border:0;background:transparent;font-size:15px;color:var(--ink);text-align:left;cursor:pointer";
    const box = (on) => h("span", { "aria-hidden": "true", style: s("flex:none;width:20px;height:20px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (on ? "var(--ink)" : "var(--line)") + ";background:" + (on ? "var(--ink)" : "var(--surface-raised)")) }, on ? raw(ROW_CHECK) : null);
    const field = (label, node) => h("label", { style: s("display:grid;gap:6px") },
      h("span", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, label), node);

    const body = phase === "creating"
      ? h("div", { key: "cr", style: s("display:grid;justify-items:center;gap:14px;padding:24px 0 28px") },
          h("span", { "aria-hidden": "true", style: s("width:34px;height:34px;border:3px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite") }),
          h("div", { role: "status", style: s("font-size:15px;font-weight:600;color:var(--ink)") }, "Creating alert…"))
      : phase === "done"
      ? h("div", { key: "dn", style: s("display:grid;justify-items:center;gap:14px;padding:6px 0 8px;text-align:center") },
          h("div", { style: s("font-size:16.5px;line-height:1.6;color:var(--ink-muted);text-wrap:pretty") }, "We’ll email new jobs as they’re posted."),
          raw(THUMB_UP))
      : h("div", { key: "fm", style: s("display:grid;gap:12px") },
          h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") }, "Get alerted when no-experience needed jobs get posted."),
          field("Email", h("input", { type: "email", value: this.state.alertEmail, onChange: this.onAlertEmail, onKeyDown: this.onAlertKey, placeholder: "you@example.com", className: "fc-bd-accent", style: s(inputStyle) })),
          field("Location", h("input", { type: "text", value: this.state.alertLoc, onChange: this.onAlertLoc, onKeyDown: this.onAlertKey, placeholder: "City or ZIP — optional", className: "fc-bd-accent", style: s(inputStyle) })),
          field("Job type", h("div", { style: s("position:relative") },
            h("button", { type: "button", onClick: this.toggleAlertCatOpen, "aria-expanded": this.state.alertCatOpen, "aria-haspopup": "true", className: "hv-bg-fact", style: s("width:100%;box-sizing:border-box;min-height:48px;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 12px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);font-size:16px;font-weight:600;color:var(--ink);cursor:pointer;text-align:left") },
              h("span", { style: s("overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, jobLabel), raw(CHEV)),
            this.state.alertCatOpen && h("div", { style: s("position:absolute;top:52px;left:0;right:0;z-index:3;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;box-shadow:0 10px 24px rgba(10,58,117,0.18);max-height:250px;overflow-y:auto;padding:4px 0") },
              h("button", { key: "all", type: "button", role: "checkbox", "aria-checked": allOn, onClick: this.alertApplyAll, className: "hv-bg-sunk", style: s(rowStyle + ";font-weight:700;border-bottom:1px solid var(--line)") }, box(allOn), h("span", null, "Apply all")),
              R.CATEGORIES.map((c, i) => { const on = cats.indexOf(c) >= 0; return h("button", { key: i, type: "button", role: "checkbox", "aria-checked": on, onClick: this.toggleAlertCat(c), className: "hv-bg-sunk", style: s(rowStyle + (on ? ";font-weight:700" : "")) }, box(on), raw(catIconSvg(c, 18)), h("span", null, c)); }))
          )),
          this.state.alertError && h("div", { key: "er", role: "alert", style: s("font-size:14px;font-weight:600;color:var(--accent)") }, this.state.alertError),
          h("button", { key: "go", type: "button", onClick: this.sendAlerts, style: s("min-height:48px;border-radius:3px;background:var(--accent);border:0;font-size:16px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--accent-ink);cursor:pointer") }, "Create alert"));

    return h("div", { style: s("position:absolute;inset:0;z-index:9") },
      h("div", { onClick: this.closeAlerts, style: s("position:absolute;inset:0;background:rgba(10,58,117,0.42);animation:scrimin 180ms ease-out") }),
      h("div", { role: "dialog", "aria-modal": "true", "aria-label": "Get new jobs by email", style: s("position:sticky;top:64px;z-index:1;width:390px;max-width:calc(100% - 32px);margin:0 auto;box-sizing:border-box;background:var(--surface);border:2px solid var(--ink);border-radius:3px;box-shadow:0 14px 30px rgba(10,58,117,0.22);display:grid;gap:12px;padding:16px;animation:sheetup 220ms cubic-bezier(.22,.61,.36,1)") },
        h("div", { style: s("display:flex;align-items:flex-start;justify-content:space-between;gap:8px") },
          h("div", { style: s("font-size:16px;font-weight:800;color:var(--ink)") }, phase === "done" ? "You’re on the list" : "Get Job Alerts"),
          h("button", { type: "button", onClick: this.closeAlerts, "aria-label": "Close", className: "hv-bg-sunk-tx-ink", style: s("flex:none;width:44px;height:44px;margin:-10px -10px 0 0;display:grid;place-items:center;background:transparent;border:0;border-radius:8px;cursor:pointer;color:var(--ink-muted)") }, raw(CLOSE))),
        body
      )
    );
  }

  render(){
    const ready = this.state.recs !== null;
    const res = ready ? L.resolveLocation(this.state.locDraft, this.state.cities, this.state.zips) : { kind: "all", cities: [] };
    const unmatched = res.kind === "unmatched" || res.kind === "unmatched-zip";
    const fresh = ready ? this.freshCount(this.state.recs || []) : 0;
    const hasFreshness = ready && fresh >= LandingApp.FRESH_FLOOR;
    const freshnessLine = fresh + (fresh === 1 ? " new job added this week" : " new jobs added this week");

    return h("div", { style: s("position:relative;display:flex;flex-direction:column;min-height:100%;background:var(--surface)") },
      h(Header, { productName: PRODUCT, onAlerts: this.openAlerts }),
      h("section", { style: s("flex:none;position:relative;background:var(--surface);border-bottom:2px solid var(--ink)") },
        h("div", { style: s("position:relative;container-type:inline-size;max-width:1120px;margin:0 auto;box-sizing:border-box;padding:0 14px 16px;display:grid;justify-items:stretch;gap:12px") },
          hasFreshness && h("div", { key: "fp", style: s("margin:0 -14px;min-height:30px;display:flex;align-items:center;justify-content:center;gap:8px;padding:4px 14px;background:var(--accent)") },
            h("span", { "aria-hidden": "true", style: s("width:7px;height:7px;border-radius:50%;background:var(--ok);flex:none;animation:livedot 2.4s ease-in-out infinite") }),
            h("span", { style: s("font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--accent-ink);text-align:center") }, freshnessLine)),
          this.renderHero(),
          this.renderSearchCard(res, unmatched)
        )
      ),
      h("main", { style: s("flex:1;max-width:1120px;width:100%;margin:0 auto;box-sizing:border-box;padding:var(--gap-section) 14px 24px;display:grid;gap:var(--gap-section);align-content:start") },
        // C3 order: the jobs come first (the reader sees the product), then "what's
        // different" explains what they just saw, then browse, then the closing CTA.
        this.renderRecent(),
        this.renderValueProps(),
        this.renderBrowse(),
        this.renderClosing()
      ),
      this.renderFooter(),
      this.renderFeedback(),
      this.renderAlerts(),
      this.state.toast && h("div", { key: "toast", role: "status", style: s("flex:none;padding:14px 20px;background:var(--ink);color:var(--accent-ink);font-size:15px;font-weight:500") }, this.state.toast)
    );
  }
}

// Mount only once the job list is in hand, seeded as initialRecs, so the first client render
// already has content matching the prerendered HTML. The baked page stays on screen during
// the fetch instead of being wiped to a blank loading state (that wipe was the load gap).
// If the fetch fails, mount anyway and let the app fall back to its own empty/loading path.
const mount = (initialRecs) => {
  const root = window.ReactDOM.createRoot(document.getElementById("root"));
  root.render(h(LandingApp, initialRecs ? { initialRecs } : null));
};
SB.listJobs().then(mount).catch(() => mount(null));
