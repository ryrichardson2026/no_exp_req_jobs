/* Alert-signup landing page — ONE job-type × market page (page 1: Washington × Retail).
   Destination for social / groups / ads; message-matched to the job type; goal is alert signups.

   Built as a copy-me template: EVERY text value lives in the CONTENT object below, so the next
   page (a different market×category) is a copy of this file with new CONTENT values, not a rebuild.
   Live data (count, max stated pay, 6 recent jobs, top employers, other-category counts) is baked
   inline by prerender/build.mjs into a <script id="__npj_data"> blob and read in boot() — no client
   query, same pattern as the landing / WA lander. Never commit the generated blob.

   Reuses the landing components + styles wholesale: Header, JobCard, Pressable, the value-prop
   and footer patterns, and styles.css. The hero's search bar is replaced by the signup form.

   Copy rules (spec): never "no resume" / "one-click apply" / "entry level"; always spell out
   "No experience needed". Signups carry NO Make changes: the page identity + channel ride in the
   existing `source` field ("alerts_wa_retail" or "alerts_wa_retail|<channel>"); market/category/UTMs
   are recorded via the GA4 event only. */
import { h, s, raw } from "./ui/h.js";
import { Header } from "./ui/header.js";
import { JobCard } from "./ui/jobCard.js";
import { Pressable } from "./ui/pressable.js";
import { catIconSvg } from "./ui/catIcons.js";
import { track, sourcePage } from "./ui/track.js";
import * as R from "./data/record.js";
import * as L from "./data/resolve.js";
import * as SB from "./data/supabase.js";
import * as RT from "./data/routes.js";

const React = window.React;
const BP = "(min-width:768px)";
const PRODUCT = "NoProbJobs.com";
// Content column. A signup/read page reads far better as a centered column than stretched across
// the full board rail (1120px) — this is what a 1920px desktop was sprawling into. The form is
// constrained narrower still (FORM_MAX). On a phone both collapse to full width.
const RAIL = "760px";
// Vertical rhythm. The .landing-scope tokens (--gap-section:12px, --gap-block:8px) are tuned tight
// for the compact landing and read as one text body on a content page — so this page sets its own
// standard spacing: generous between sections, clear between the info subsections.
const GAP_SECTION = "42px";   // between top-level sections
const GAP_SUB = "28px";       // between the info block's subsections
const GAP_BLOCK = "15px";     // header -> content within a section

// ────────────────────────────────────────────────────────────────────────────
// CONTENT — the ONLY place to edit for the next page. Copy this file, change these values.
// ────────────────────────────────────────────────────────────────────────────
const CONTENT = {
  // ── identity (must match a data/record.js CATEGORIES value + a launched market) ──
  market: "WA",
  marketName: "Washington",
  marketSlug: "washington",
  category: "Retail",
  categoryName: "Retail",
  categoryNoun: "retail",
  listingPath: "/washington/retail/",

  // ── meta ──
  metaTitle: "Retail Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Retail jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",

  // ── hero ──
  h1: "Get Retail Job Alerts",
  heroSub: "Be first to know when new No Experience Required Retail Jobs show up in your area.",
  formButton: "Get free alerts",
  // Cadence microcopy. The automated send is a parallel phase-2 build, so no schedule is promised:
  // "as they’re posted" -> "New jobs as they’re posted. Unsubscribe anytime."
  // Switch to "weekly"/"daily" once the Make → MailerLite flow enforces one.
  cadence: "as they’re posted",

  // ── Why NoProbJobs (value props) ──
  valueProps: [
    ["100% free", "Always free for job seekers."],
    ["No sign-up needed to apply", "Apply directly with the employer."],
    ["Real employers, real jobs", "Every job comes from the company’s own careers page."],
    ["Requirements up front", "Spend less time searching and more time applying."],
    ["Pay transparency", "Shown when the employer states it. Never estimated."],
  ],
  secondSignupHeading: "Get new retail jobs before they fill.",

  // ── "Retail with no experience in Washington" ──
  info: {
    heading: "The Retail Job Market in Washington State",

    whatTheWork: "Retail jobs put you on a store floor: helping customers, running a register, stocking shelves, keeping the store in order, and processing returns or online pickup orders. Most stores train you on the job. You need to be reliable, friendly with customers, and available for the shifts they need.",

    payHeading: "What retail pays in Washington",
    payIntro: "Washington has the highest statewide minimum wage in the country, so retail pay here starts higher than almost anywhere else.",
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Cities above the state rate", "Tukwila, SeaTac, Renton, Burien, Everett, Bellingham, and unincorporated King County", null],
      ["Retail salespersons, Washington", "Typically $22/hr; half earn $18–$24/hr", null],
      ["Cashiers, Washington", "Average $22/hr; half earn $17–$23/hr", null],
      ["Retail supervisors, Washington", "Typically $30/hr; half earn $20–$33/hr", null],
    ],
    payPartTime: "Most retail workers in Washington are part-time: about 85% of retail salespersons worked part-time in the past year.",
    payWhy: "Washington law requires employers with 15 or more employees to post a wage range and a description of benefits on every job posting. On NoProbJobs, pay is shown only when the employer states it — never estimated.",

    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Retail hiring in Washington comes from national chains, discount stores and specialty shops. See every current opening on the retail board.",
    seasonalNote: "Retailers commonly add seasonal staff ahead of the holidays, and seasonal roles are some of the easiest retail jobs to get with no experience.",

    stepsHeading: "How hiring usually works",
    stepsIntro: "Every store is different, but most retail hiring follows the same few steps:",
    steps: [
      ["Apply online.", "You’ll enter your contact info and your availability. Availability matters a lot in retail hiring, so be accurate and as open as you can."],
      ["Short assessment (sometimes).", "Some large retailers ask situational questions about customer service and teamwork."],
      ["Recorded video interview (sometimes).", "Some large chains send a link to record answers to a few questions on your phone."],
      ["Interview with a manager.", "Often short and in person. Expect questions like “Tell me about a time you helped someone” or “What does good customer service mean to you?” School, volunteer or life examples count."],
      ["Background check, then start.", "For hourly store roles, the whole process often takes one to two weeks."],
    ],

    tipsHeading: "How to land a retail job with no experience",
    tips: [
      ["Lead with availability.", "Evenings, weekends and holidays are the shifts stores most need to fill."],
      ["Apply to several stores at once.", "Retail hires fast and often. Don’t wait on one application."],
      ["Answer with real examples.", "Helping a neighbor, a school project, a volunteer shift. Managers want to see you’re reliable and good with people."],
      ["Show up like it’s the job.", "On time, phone away, ready to talk about when you can work."],
      ["Follow up.", "If you haven’t heard back in a few days, a short call or visit to the store is normal in retail."],
      ["Consider seasonal roles.", "They’re easier to get, and stores often keep strong seasonal workers."],
    ],

    leadsHeading: "Where retail can lead",
    leadsIntro: "Many retail workers move up within the store:",
    leadsPath: ["Sales associate / cashier", "Shift lead or key holder (opens and closes the store, runs a shift)", "Supervisor or department lead (typically $30/hr in Washington)", "Assistant store manager / store manager"],
    leadsNote: "Retail experience also carries over to customer service roles, which in Washington typically pay around $28/hr.",
  },

  // ── FAQ (emitted as FAQPage JSON-LD) ──
  faqHeading: "Getting Hired in Retail FAQ",
  faq: [
    ["Do I need experience to get a retail job in Washington?", "No. Most first-time retail roles — sales associate, cashier and stocker — train you on the job. Every job on this page is marked as not requiring experience."],
    ["How much do retail jobs pay in Washington?", "At least $17.13 an hour statewide in 2026, and more in cities with higher minimums, like Seattle at $21.30. Retail salespersons in Washington typically earn about $22 an hour."],
    ["Are most retail jobs part-time?", "Many are. About 85% of retail salespersons in Washington worked part-time in the past year. Full-time roles are available and are labeled on each job."],
    ["Will I need a resume?", "Many employers ask for one in their application. You don’t need one to browse or get alerts on NoProbJobs."],
    ["How fast can I get hired?", "For hourly store roles, often within one to two weeks from applying. Seasonal hiring can move faster."],
  ],
};

// UTM for every outbound listing link (spec).
const LINK_UTM = "utm_source=alerts_page&utm_medium=internal&utm_campaign=" + CONTENT.market.toLowerCase() + "_" + CONTENT.categoryNoun;
function withUtm(path){ return path + (path.indexOf("?") >= 0 ? "&" : "?") + LINK_UTM; }

const CHEV = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="currentColor" stroke-width="1.6" style="flex:none" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const CHEV_MUTED = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="var(--ink-muted)" stroke-width="1.6" style="flex:none" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const ROW_CHECK = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="var(--accent-ink)" stroke-width="2.2" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';
const VP_CHECK = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--mark-ink)" stroke-width="1.9"><circle cx="8" cy="8" r="6.6"></circle><path d="M5 8.3l2.1 2.1L11 6.1"></path></svg>';
const ARROW = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="2.2" style="flex:none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"></path></svg>';
const TICK = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="2.6" style="flex:none" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';

class AlertsApp extends React.Component {
  constructor(props){
    super(props);
    this.data = props.data || { count: 0, maxPay: null, recent: [], otherCats: [], whosHiring: [], seasonalCount: 0, pulledAt: null };
    this.state = {
      email: "", location: "",
      cats: [CONTENT.category],
      catOpen: false,
      phase: "form", error: "",
      logoOk: {},
      wide: window.matchMedia(BP).matches,
    };
    this.formRef = React.createRef();
    this.utm = this.readUtm();
  }

  readUtm(){
    const out = { utm_source: null, utm_medium: null, utm_campaign: null, utm_content: null, utm_term: null };
    try { const p = new URL(window.location.href).searchParams; Object.keys(out).forEach((k) => { out[k] = p.get(k); }); } catch (e) {}
    return out;
  }
  pagePath(){ try { return window.location.pathname || CONTENT.listingPath; } catch (e) { return CONTENT.listingPath; } }
  // Page + channel encoded into the existing `source` field — no Make changes. Channel from the
  // inbound utm_source (fb_groups, reddit, …): "alerts_wa_retail" or "alerts_wa_retail|fb_groups".
  signupSource(){
    const base = "alerts_" + CONTENT.market.toLowerCase() + "_" + CONTENT.categoryNoun;
    const ch = (this.utm.utm_source || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
    return ch ? base + "|" + ch : base;
  }

  componentDidMount(){
    this._mql = window.matchMedia(BP);
    this._onMql = () => this.setState({ wide: this._mql.matches });
    this._mql.addEventListener("change", this._onMql);
    window.addEventListener("mousedown", this.onDocDown, true);
    this.preflightLogos(this.data.recent || []);
  }
  componentWillUnmount(){
    if (this._mql) this._mql.removeEventListener("change", this._onMql);
    window.removeEventListener("mousedown", this.onDocDown, true);
    clearTimeout(this._t);
  }
  onDocDown = (e) => {
    if (!this.state.catOpen) return;
    const t = e.target;
    if (t && t.closest && (t.closest("[data-cat-pop]") || t.closest("[data-cat-trigger]"))) return;
    this.setState({ catOpen: false });
  };

  preflightLogos(recs){
    const seen = {};
    recs.forEach((r) => {
      if (R.localLogo(r.company_name)) return;
      const d = r.employer_domain;
      if (!d || seen[d] || !R.ownsDomain(r.company_name, d)) return;
      seen[d] = true;
      const img = new Image();
      img.onerror = () => {};
      img.onload = () => { if (img.naturalWidth < 16) return; this.setState((st) => { const ok = Object.assign({}, st.logoOk); ok[d] = true; return { logoOk: ok }; }); };
      img.src = R.logoUrl(d);
    });
  }

  // ── form handlers ─────────────────────────────────────────
  onEmail = (e) => this.setState({ email: e.target.value });
  onLocation = (e) => this.setState({ location: e.target.value });
  toggleCatOpen = () => this.setState({ catOpen: !this.state.catOpen });
  toggleCat = (c) => () => {
    const cur = this.state.cats || [];
    const next = cur.indexOf(c) >= 0 ? cur.filter((x) => x !== c) : cur.concat([c]);
    this.setState({ cats: next });
  };
  onKey = (e) => { if (e.key === "Enter") { e.preventDefault(); this.submit(); } };
  scrollToForm = () => { try { if (this.formRef.current) this.formRef.current.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {} };

  submit = () => {
    const email = (this.state.email || "").trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { this.setState({ phase: "form", error: "Enter a valid email address." }); return; }
    const location = (this.state.location || "").trim();
    if (!location) { this.setState({ phase: "form", error: "Enter a city or ZIP." }); return; }   // accepted even outside live markets — demand data
    const categories = (this.state.cats && this.state.cats.length) ? this.state.cats : [CONTENT.category];
    this.setState({ phase: "creating", error: "", catOpen: false });
    const wait = new Promise((r) => { this._t = setTimeout(r, 2000); });
    Promise.all([SB.captureAlert({ email, source: this.signupSource(), location, categories }), wait])
      .then(() => {
        // Full context (market/category/channel) recorded on the GA4 event; Make gets it via `source`.
        track(Object.assign({ event: "alert_signup", source_page: sourcePage(), market: CONTENT.market, category: CONTENT.category },
          this.utm.utm_source ? { channel: this.utm.utm_source } : {}));
        this.setState({ phase: "done" });
      })
      .catch(() => this.setState({ phase: "form", error: "Couldn’t save that — please try again." }));
  };

  // ── card shaping (mirrors landing.shape) ──────────────────
  shape(r){
    const domain = r.employer_domain || "";
    const local = R.localLogo(r.company_name);
    const logoSrc = local || R.logoUrl(domain);
    const showLogo = local ? true : (R.ownsDomain(r.company_name, domain) && !!this.state.logoOk[domain]);
    const jobHref = RT.jobPath(r) + "/";
    return Object.assign({}, r, {
      id: r.internal_id,
      company: R.companyLabel(r.company_name),
      cardTitle: R.cardTitle(r.title),
      logoImg: showLogo ? R.logoImg(logoSrc, 20) : null,
      showLogo, showMonogram: !showLogo,
      monogram: (r.company_name || "?").trim().charAt(0).toUpperCase(),
      locationLine: [L.cityName(r.city), r.state].filter(Boolean).join(", "),
      pay: R.money(r), posted: R.postedLabel(r.posted_at),
      isNew: !!r.is_new,
      expLabel: R.EXP_LABEL[r.experience_condition] || null,
      expStrong: r.experience_condition === "NONE_NEEDED" || r.experience_condition === "WAIVED",
      expSoft: r.experience_condition === "PREFERRED",
      href: jobHref,
      onCardClick: (e) => { if (e && (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1)) return; if (e && e.preventDefault) e.preventDefault(); window.location.href = jobHref; },
      isSelected: false, open: () => { window.location.href = jobHref; },
      openKey: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); window.location.href = jobHref; } },
    });
  }

  // ── hero + signup form ────────────────────────────────────

  workTypeSelect(inputStyle){
    const picked = this.state.cats || [];
    const open = this.state.catOpen;
    const summary = picked.length ? (picked.length > 2 ? picked.slice(0, 2).join(", ") + " +" + (picked.length - 2) : picked.join(", ")) : CONTENT.categoryName;
    const checkbox = (on) => on
      ? h("span", { "aria-hidden": "true", style: s("flex:none;width:18px;height:18px;border-radius:3px;background:var(--ink);display:grid;place-items:center") }, raw(ROW_CHECK))
      : h("span", { "aria-hidden": "true", style: s("flex:none;width:18px;height:18px;border-radius:3px;border:1px solid var(--ink);background:var(--surface-raised)") });
    return h("div", { style: s("position:relative"), "data-cat-pop": "true" },
      h("button", { type: "button", "data-cat-trigger": "true", onClick: this.toggleCatOpen, "aria-expanded": open, "aria-haspopup": "true", className: "fc-bd-accent",
          style: s(inputStyle + ";display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer;text-align:left;font-weight:700") },
        h("span", { style: s("overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, summary), raw(open ? CHEV : CHEV_MUTED)),
      open && h("div", { role: "group", "aria-label": "Work type", style: s("margin-top:6px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);max-height:230px;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:6px") },
        h("div", { style: s("display:grid;grid-template-columns:1fr 1fr;gap:1px 8px") },
          R.CATEGORIES.map((c, i) => { const on = picked.indexOf(c) >= 0; return h("button", { key: i, type: "button", role: "checkbox", "aria-checked": on, onClick: this.toggleCat(c), className: "hv-bg-sunk",
              style: s("display:flex;align-items:center;gap:7px;min-height:38px;padding:0 5px;background:transparent;border:0;border-radius:3px;cursor:pointer;text-align:left") },
            checkbox(on),
            h("span", { style: s("flex:1;font-size:13px;font-weight:" + (on ? "700" : "500") + ";line-height:1.15;color:var(--ink)") }, c)); }))));
  }

  renderHeroForm(){
    // Softer than the site's brutalist box (per the CEO's landingfolio reference): 1px light
    // borders, rounded corners, generous spacing, a subtle lift — a clean signup card.
    const inputStyle = "box-sizing:border-box;width:100%;min-height:50px;padding:0 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);font-size:15px;color:var(--ink);outline:0";
    const field = (label, node) => h("label", { style: s("display:grid;gap:6px") },
      h("span", { style: s("font-size:12.5px;font-weight:700;letter-spacing:0.02em;color:var(--ink-muted)") }, label), node);
    const card = "width:100%;box-sizing:border-box;background:var(--surface-raised);border:1px solid var(--line);border-radius:16px;box-shadow:0 16px 44px rgba(10,58,117,0.13);padding:24px;display:grid;gap:14px";
    const cta = "min-height:52px;border-radius:11px;background:var(--accent);border:0;font-size:16px;font-weight:800;letter-spacing:0.01em;color:var(--accent-ink);text-decoration:none;display:flex;align-items:center;justify-content:center;gap:10px";
    const cadence = CONTENT.cadence;
    const microcopy = "Get Notified about New Jobs. Unsubscribe anytime.";

    if (this.state.phase === "done") {
      return h("div", { ref: this.formRef, style: s(card + ";justify-items:center;text-align:center;padding:30px 24px;gap:12px") },
        h("img", { src: "/logo.png", alt: "", width: 52, height: 52, style: s("width:52px;height:52px;object-fit:contain") }),
        h("div", { style: s("font-size:19px;font-weight:800;color:var(--ink)") }, "You’re on the list"),
        h("div", { style: s("font-size:15px;line-height:1.6;color:var(--ink-muted);text-wrap:pretty") }, "We’ll email new " + CONTENT.categoryNoun + " jobs " + cadence + "."),
        h("a", { href: withUtm(CONTENT.listingPath), style: s(cta + ";padding:0 22px") }, "See " + CONTENT.categoryNoun + " jobs"));
    }

    const creating = this.state.phase === "creating";
    return h("div", { ref: this.formRef, style: s(card) },
      h("div", { style: s("display:grid;gap:3px") },
        h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:19px;line-height:1.15;color:var(--ink)") }, "Free job alerts"),
        h("div", { style: s("font-size:13.5px;color:var(--ink-muted)") }, "New " + CONTENT.categoryNoun + " jobs, straight to your inbox.")),
      field("Email", h("input", { type: "email", value: this.state.email, onChange: this.onEmail, onKeyDown: this.onKey, placeholder: "you@example.com", className: "fc-bd-accent", disabled: creating, style: s(inputStyle) })),
      field("City or ZIP", h("input", { type: "text", value: this.state.location, onChange: this.onLocation, onKeyDown: this.onKey, placeholder: "e.g. Seattle or 98101", "aria-label": "City or ZIP", className: "fc-bd-accent", disabled: creating, style: s(inputStyle) })),
      field("Work type", this.workTypeSelect(inputStyle)),
      this.state.error && h("div", { role: "alert", style: s("font-size:14px;font-weight:600;color:var(--accent)") }, this.state.error),
      h("button", { type: "button", onClick: this.submit, disabled: creating, style: s(cta + ";cursor:" + (creating ? "default" : "pointer")) },
        creating ? h("span", { "aria-hidden": "true", style: s("width:20px;height:20px;border:3px solid rgba(255,255,255,0.4);border-top-color:var(--accent-ink);border-radius:50%;animation:spin 0.8s linear infinite") }) : null,
        creating ? "Creating alert…" : CONTENT.formButton),
      h("div", { style: s("font-size:12.5px;line-height:1.4;color:var(--ink-muted);text-align:center") }, microcopy));
  }

  renderHero(){
    const wide = this.state.wide;
    const payPill = this.data.maxPay
      ? h("span", { style: s("justify-self:start;display:inline-flex;align-items:center;padding:5px 12px;border-radius:999px;background:var(--mark);color:var(--mark-ink);font-size:13px;font-weight:800;letter-spacing:0.01em") }, "Up to $" + this.data.maxPay + " an hour")
      : null;
    const countLine = this.data.count
      ? h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") },
          h("strong", { style: s("color:var(--ink)") }, this.data.count.toLocaleString()), " " + CONTENT.categoryNoun + " jobs hiring in " + CONTENT.marketName + " right now. ",
          h("a", { href: withUtm(CONTENT.listingPath), style: s("font-weight:800;color:var(--accent);white-space:nowrap") }, "See Jobs →"))
      : null;
    const ticks = h("div", { style: s("display:flex;flex-wrap:wrap;gap:9px 18px;font-size:13px;font-weight:700;color:var(--ink)") },
      ["100% free", "No sign-up to apply", "Real employers"].map((t, i) => h("span", { key: i, style: s("display:inline-flex;align-items:center;gap:5px") }, raw(TICK), t)));
    const copy = h("div", { style: s("display:grid;gap:15px;align-content:center") },
      payPill,
      h("h1", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:" + (wide ? "44px" : "31px") + ";line-height:1.04;letter-spacing:-0.015em;color:var(--ink)") }, CONTENT.h1),
      h("div", { style: s("font-size:" + (wide ? "17.5px" : "15.5px") + ";line-height:1.5;color:var(--ink-muted);text-wrap:pretty;max-width:36ch") }, CONTENT.heroSub),
      ticks,
      countLine);
    const form = h("div", { style: s("width:100%;max-width:" + (wide ? "430px" : "520px") + ";justify-self:" + (wide ? "end" : "center")) }, this.renderHeroForm());
    return h("section", { style: s("flex:none;background:linear-gradient(180deg,var(--fact) 0%,var(--surface) 60%);border-bottom:2px solid var(--ink)") },
      h("div", { style: s("max-width:1060px;margin:0 auto;box-sizing:border-box;padding:" + (wide ? "48px 24px 54px" : "24px 16px 30px") + ";display:grid;gap:" + (wide ? "48px" : "22px") + ";" + (wide ? "grid-template-columns:1.05fr 430px;align-items:center" : "grid-template-columns:1fr")) },
        copy, form));
  }

  // ── recent jobs ───────────────────────────────────────────
  renderRecent(){
    const jobs = (this.data.recent || []).map((r) => this.shape(r));
    if (!jobs.length) return null;
    return h("section", { style: s("display:grid;gap:" + GAP_BLOCK) },
      h("h2", { style: s(sectionH2) }, "Recent " + CONTENT.categoryNoun + " jobs"),
      h("div", { role: "list", style: s("display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:12px") },
        jobs.map((job) => h(Pressable, { key: job.id, tag: "div",
            styleFor: (pd) => s("display:flex;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;transition:transform 45ms ease-out,box-shadow 45ms ease-out;"
              + (pd ? "transform:translate(4px,4px);box-shadow:0 0 0 0 var(--ink)" : "box-shadow:4px 4px 0 0 var(--ink)")) },
          h("div", { style: s("flex:1;min-width:0") }, h(JobCard, { job, flush: true }))))),
      this.data.count ? h("a", { href: withUtm(CONTENT.listingPath), style: s("justify-self:start;min-height:44px;display:inline-flex;align-items:center;font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.03em;color:var(--accent)") }, "See all " + this.data.count.toLocaleString() + " " + CONTENT.categoryNoun + " jobs") : null);
  }

  // ── info block ────────────────────────────────────────────
  para(txt){ return h("p", { style: s("margin:0;font-size:15.5px;line-height:1.6;color:var(--ink);text-wrap:pretty") }, txt); }
  subH(txt){ return h("h3", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:17px;line-height:1.25;color:var(--ink)") }, txt); }

  renderPayTable(){
    const info = CONTENT.info;
    return h("div", { style: s("display:grid;gap:8px") },
      info.payTable.map(([label, val, note], i) => h("div", { key: i, style: s("display:grid;grid-template-columns:1fr;gap:2px;padding:10px 0;border-top:1px solid var(--line)") },
        h("div", { style: s("font-size:14px;font-weight:700;color:var(--ink)") }, label),
        h("div", { style: s("font-size:15px;color:var(--ink)") }, val),
        note ? h("div", { style: s("font-size:12.5px;color:var(--ink-muted)") }, note) : null)));
  }

  renderWhosHiring(){
    const info = CONTENT.info;
    const hiring = this.data.whosHiring || [];
    const seasonal = this.data.seasonalCount || 0;
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(info.whosHiringHeading),
      hiring.length
        ? h("div", { style: s("display:grid;gap:8px") },
            hiring.map((e, i) => h("a", { key: i, href: withUtm(e.href), className: "hv-bg-sunk", style: s("display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid var(--line);border-radius:3px;text-decoration:none") },
              h("span", { style: s("font-size:15px;font-weight:700;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, e.company),
              h("span", { style: s("flex:none;font-size:13px;font-weight:700;color:var(--accent)") }, e.count.toLocaleString() + (e.count === 1 ? " job" : " jobs")))))
        : this.para(info.whosHiringFallback),
      this.para(info.seasonalNote + (seasonal ? " " + seasonal.toLocaleString() + " seasonal " + (seasonal === 1 ? "role is" : "roles are") + " open right now." : "")));
  }

  renderList(heading, intro, rows){
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(heading),
      intro ? this.para(intro) : null,
      h("ol", { style: s("margin:0;padding:0;list-style:none;display:grid;gap:10px;counter-reset:step") },
        rows.map(([lead, body], i) => h("li", { key: i, style: s("display:flex;gap:10px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;width:24px;height:24px;border-radius:50%;background:var(--ink);color:var(--surface);display:grid;place-items:center;font-size:13px;font-weight:800") }, String(i + 1)),
          h("div", { style: s("font-size:15.5px;line-height:1.55;color:var(--ink);text-wrap:pretty") }, h("strong", null, lead), " " + body)))));
  }

  renderTips(){
    const info = CONTENT.info;
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(info.tipsHeading),
      h("ul", { style: s("margin:0;padding:0;list-style:none;display:grid;gap:8px") },
        info.tips.map(([lead, body], i) => h("li", { key: i, style: s("display:flex;gap:9px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;margin-top:5px;width:16px;height:16px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(ROW_CHECK)),
          h("div", { style: s("font-size:15.5px;line-height:1.55;color:var(--ink);text-wrap:pretty") }, h("strong", null, lead), " " + body)))));
  }

  renderLeads(){
    const info = CONTENT.info;
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(info.leadsHeading),
      this.para(info.leadsIntro),
      h("div", { style: s("display:flex;flex-wrap:wrap;align-items:center;gap:8px") },
        info.leadsPath.map((step, i) => [
          i ? h("span", { key: "a" + i, "aria-hidden": "true", style: s("display:inline-flex") }, raw(ARROW)) : null,
          h("span", { key: "s" + i, style: s("padding:6px 11px;border:1px solid var(--ink);border-radius:3px;background:var(--surface-raised);font-size:13.5px;font-weight:700;color:var(--ink)") }, step),
        ])),
      this.para(info.leadsNote));
  }

  renderInfo(){
    const info = CONTENT.info;
    return h("section", { style: s("display:grid;gap:" + GAP_SUB) },
      h("h2", { style: s(sectionH2) }, info.heading),
      // What the work is
      this.para(info.whatTheWork),
      // Pay
      h("div", { style: s("display:grid;gap:10px") },
        this.subH(info.payHeading),
        this.para(info.payIntro),
        this.renderPayTable(),
        this.para(info.payPartTime),
        h("div", { style: s("padding:12px 14px;background:var(--fact);border:1px solid var(--ink);border-radius:3px;font-size:14.5px;line-height:1.55;color:var(--fact-ink);text-wrap:pretty") }, h("strong", null, "Why you can see the pay: "), info.payWhy)),
      // Who's hiring + seasonal
      this.renderWhosHiring(),
      // How hiring works
      this.renderList(info.stepsHeading, info.stepsIntro, info.steps),
      // Tips
      this.renderTips(),
      // Where retail can lead
      this.renderLeads());
  }

  // ── why NoProbJobs ────────────────────────────────────────
  renderValueProps(){
    const items = CONTENT.valueProps;
    const grid = this.state.wide ? "repeat(auto-fit,minmax(min(320px,100%),1fr))" : "1fr";
    return h("section", { style: s("margin:0 -14px;padding:16px 14px;background:var(--ink);display:grid;gap:14px") },
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:16px;letter-spacing:0.04em;text-transform:uppercase;color:var(--mark)") }, "Why No Prob Jobs"),
      h("div", { style: s("display:grid;grid-template-columns:" + grid + ";gap:10px 20px") },
        items.map(([t, b], i) => h("div", { key: i, style: s("display:flex;gap:10px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;width:32px;height:32px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(VP_CHECK)),
          h("div", { style: s("display:grid;gap:3px;min-width:0") },
            h("div", { style: s("font-size:16px;font-weight:700;color:var(--surface)") }, t),
            h("div", { style: s("font-size:15px;line-height:1.35;color:var(--line);text-wrap:pretty") }, b))))));
  }

  renderSecondSignup(){
    return h("section", { style: s("margin:0 -14px;padding:18px 14px;background:var(--mark);display:grid;gap:12px;justify-items:center;text-align:center") },
      h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:18px;line-height:1.25;color:var(--mark-ink)") }, CONTENT.secondSignupHeading),
      h(Pressable, { tag: "button", onClick: this.scrollToForm, className: "hv-underline-none",
          styleFor: (pd) => s("min-height:48px;display:inline-flex;align-items:center;padding:0 24px;border:0;background:var(--accent);font-size:15px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--accent-ink);cursor:pointer;white-space:nowrap;transition:box-shadow 40ms ease-out,transform 40ms ease-out;box-shadow:"
            + (pd ? "inset -3px -3px 0 0 var(--accent-lite),inset 3px 3px 0 0 var(--accent-dark);transform:translate(1px,1px)" : "inset 3px 3px 0 0 var(--accent-lite),inset -3px -3px 0 0 var(--accent-dark)")) }, CONTENT.formButton));
  }

  // ── browse other work types ───────────────────────────────
  renderBrowse(){
    const cards = (this.data.otherCats || []).filter((c) => c.label !== CONTENT.category);
    const cols = this.state.wide ? "repeat(3,1fr)" : "1fr 1fr";
    return h("section", { style: s("display:grid;gap:" + GAP_BLOCK) },
      h("h2", { style: s(sectionH2) }, "Browse other work types"),
      cards.length ? h("div", { style: s("display:grid;grid-template-columns:" + cols + ";grid-auto-rows:1fr;gap:12px") },
        cards.map((c, i) => h("div", { key: i, style: s("position:relative") },
          h("span", { "aria-hidden": "true", style: s("position:absolute;inset:0;transform:translate(4px,4px);background:var(--mark);border:2px solid var(--ink);border-radius:3px") }),
          h(Pressable, { tag: "a", href: withUtm(c.href), className: "hv-bg-fact",
              styleFor: (pd) => s("position:relative;height:100%;box-sizing:border-box;display:grid;align-content:start;gap:7px;min-height:66px;padding:14px;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;text-decoration:none;transition:transform 45ms ease-out;" + (pd ? "transform:translate(4px,4px)" : "")) },
            raw(catIconSvg(c.label, 24)),
            h("div", { style: s("display:grid;gap:2px") },
              h("span", { style: s("font-family:var(--font-display);font-weight:800;font-size:16px;line-height:1.2;color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:38px") }, c.displayLabel || c.label),
              h("span", { style: s("font-size:13px;line-height:1.35;font-weight:700;color:var(--accent);min-height:18px") }, c.count ? (c.count.toLocaleString() + (c.count === 1 ? " job" : " jobs")) : "")))))) : null,
      h("a", { href: withUtm("/" + CONTENT.marketSlug + "/"), style: s("justify-self:start;min-height:44px;display:inline-flex;align-items:center;font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.03em;color:var(--accent)") }, "Browse all jobs"));
  }

  // ── FAQ (+ FAQPage JSON-LD) ───────────────────────────────
  faqSchema(){
    return {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      "mainEntity": CONTENT.faq.map(([q, a]) => ({ "@type": "Question", "name": q, "acceptedAnswer": { "@type": "Answer", "text": a } })),
    };
  }
  renderFaq(){
    return h("section", { style: s("display:grid;gap:" + GAP_BLOCK) },
      h("h2", { style: s(sectionH2) }, CONTENT.faqHeading),
      h("div", { style: s("display:grid;gap:12px") },
        CONTENT.faq.map(([q, a], i) => h("div", { key: i, style: s("display:grid;gap:4px;padding-bottom:12px;border-bottom:1px solid var(--line)") },
          h("div", { style: s("font-size:16px;font-weight:700;color:var(--ink)") }, q),
          h("div", { style: s("font-size:15px;line-height:1.55;color:var(--ink-muted);text-wrap:pretty") }, a)))),
      // JSON-LD baked into the DOM (search engines read it anywhere in the document).
      h("script", { type: "application/ld+json", dangerouslySetInnerHTML: { __html: JSON.stringify(this.faqSchema()) } }));
  }

  renderFooter(){
    return h("footer", { style: s("flex:none;background:var(--ink)") },
      h("div", { style: s("max-width:var(--rail,1120px);margin:0 auto;padding:14px;display:grid;justify-items:center;gap:6px") },
        h("div", { style: s("font-size:14px;font-weight:600;color:var(--line);text-align:center") }, "Free for job seekers. No signup required to apply."),
        h("a", { href: RT.PRIVACY_URL, target: "_blank", rel: "noopener noreferrer", style: s("min-height:44px;display:inline-flex;align-items:center;font-size:13px;font-weight:500;color:var(--line)") }, "Privacy Policy")));
  }

  render(){
    return h("div", { className: "landing-scope", style: s("position:relative;display:flex;flex-direction:column;min-height:100%;background:var(--surface)") },
      h(Header, { productName: PRODUCT, alertsInHeader: false }),
      this.renderHero(),
      h("main", { style: s("flex:1;max-width:" + RAIL + ";width:100%;margin:0 auto;box-sizing:border-box;padding:38px 16px 44px;display:grid;gap:" + GAP_SECTION + ";align-content:start") },
        this.renderRecent(),
        this.renderInfo(),
        this.renderFaq(),
        this.renderValueProps(),
        this.renderSecondSignup(),
        this.renderBrowse()),
      this.renderFooter());
  }
}

const sectionH2 = "margin:0 0 3px;font-family:var(--font-display);font-weight:800;font-size:19px;line-height:1.2;letter-spacing:0.01em;color:var(--ink);padding-bottom:10px;border-bottom:2px solid var(--mark)";

const mount = (data) => {
  const root = window.ReactDOM.createRoot(document.getElementById("root"));
  root.render(h(AlertsApp, { data }));
};
// Data ships INLINE (baked by prerender/build.mjs) — no client query. Set today from the baked
// pulledAt before first render, then mount. Fall back to an empty scaffold if the blob is missing.
const boot = () => {
  const el = document.getElementById("__npj_data");
  if (el) {
    try {
      const d = JSON.parse(el.textContent);
      if (d.pulledAt) R.setToday(d.pulledAt);
      mount(d);
      return;
    } catch (e) { /* malformed blob -> render empty scaffold */ }
  }
  mount({ count: 0, maxPay: null, recent: [], otherCats: [], whosHiring: [], seasonalCount: 0, pulledAt: null });
};
boot();
