/* Static content pages: /about/ and /partners/. Reuses the alert-lander template chrome and
   styles (Header, siteFooter, breadcrumb, H2 section styling, hero gradient, the soft form card,
   fonts, CSS variables) so nothing new is invented visually. One module renders both pages; it
   picks which from the inlined __npj_data blob (baked by prerender/build.mjs) or the URL path.

   The contact form POSTs to the same Make webhook the alert signups use, with a hidden
   source_page ("about" | "partners") so a Make router can split contact submissions from alert
   signups. No page reload; no other storage. The logo carousel renders the brand list the bake
   inlines (every /logos/ file except aboutusimage.png, plus Shake Shack / Jimmy John's / Walmart
   only when they have live jobs). */
import { h, s } from "./ui/h.js";
import { Header } from "./ui/header.js";
import { Pressable } from "./ui/pressable.js";
import { siteFooter } from "./ui/siteFooter.js";
import { logoCarousel } from "./ui/logoCarousel.js";

const React = window.React;
const PRODUCT = "NoProbJobs.com";
const RAIL = "760px";
const ORIGIN = "https://noprobjobs.com";
const ALERTS_HUB = "/alerts/washington/";
const MAKE_HOOK = "https://hook.us2.make.com/o30dw0i6emep7uaurcg6lf2i5kdkg6o3";

// ---- shared style strings (copied verbatim from the alert template so styling matches) ----
const sectionH2 = "margin:0 0 3px;font-family:var(--font-display);font-weight:800;font-size:19px;line-height:1.2;letter-spacing:0.01em;color:var(--ink);padding-bottom:10px;border-bottom:2px solid var(--mark)";
const H1 = "margin:0;font-family:var(--font-display);font-weight:800;font-size:31px;line-height:1.08;letter-spacing:-0.015em;color:var(--ink)";
const PARA = "margin:0;font-size:16px;line-height:1.6;color:var(--ink-muted);text-wrap:pretty";
const LINK = "color:var(--accent);font-weight:700;text-decoration:none";
const card = "width:100%;box-sizing:border-box;background:var(--surface-raised);border:1px solid var(--line);border-radius:16px;box-shadow:0 16px 44px rgba(10,58,117,0.13);padding:24px;display:grid;gap:14px";
const inputStyle = "box-sizing:border-box;width:100%;min-height:50px;padding:0 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);font-size:15px;color:var(--ink);outline:0";
const areaStyle = "box-sizing:border-box;width:100%;min-height:120px;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);font-size:15px;line-height:1.5;color:var(--ink);outline:0;resize:vertical;font-family:inherit";
const cta = "min-height:52px;border-radius:11px;background:var(--accent);border:0;font-size:16px;font-weight:800;letter-spacing:0.01em;color:var(--accent-ink);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:10px";

function postContact(payload){
  return fetch(MAKE_HOOK, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(Object.assign({ captured_at: new Date().toISOString() }, payload)),
  }).then((res) => { if (!res.ok) throw new Error("contact " + res.status); return true; });
}

class PagesApp extends React.Component {
  constructor(props){
    super(props);
    this.page = props.page === "partners" ? "partners" : "about";
    this.data = props.data || {};
    this.state = { name: "", email: "", organization: "", message: "", phase: "form", error: "" };
  }

  set = (k) => (e) => this.setState({ [k]: e.target.value });

  submit = () => {
    const name = (this.state.name || "").trim();
    const email = (this.state.email || "").trim();
    const message = (this.state.message || "").trim();
    if (!name) { this.setState({ error: "Enter your name." }); return; }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { this.setState({ error: "Enter a valid email address." }); return; }
    if (!message) { this.setState({ error: "Enter a message." }); return; }
    this.setState({ phase: "sending", error: "" });
    const payload = { source_page: this.page, name, email, organization: (this.state.organization || "").trim(), message };
    const wait = new Promise((r) => { setTimeout(r, 900); });
    Promise.all([postContact(payload), wait])
      .then(() => this.setState({ phase: "done" }))
      .catch(() => this.setState({ phase: "form", error: "Could not send that. Please try again." }));
  };

  // ── breadcrumb (matches the alert pages: same markup, styling, BreadcrumbList JSON-LD) ──
  breadcrumbSchema(label, path){
    const items = [
      { name: "No-Experience Jobs", url: ORIGIN + "/" },
      { name: label, url: ORIGIN + path },
    ];
    return { "@context": "https://schema.org", "@type": "BreadcrumbList",
      itemListElement: items.map((it, i) => ({ "@type": "ListItem", position: i + 1, name: it.name, item: it.url })) };
  }
  renderBreadcrumb(label, path){
    const link = s("min-height:34px;display:inline-flex;align-items:center;color:var(--accent);text-decoration:none;font-weight:700");
    return h("nav", { "aria-label": "Breadcrumb", style: s("display:flex;flex-wrap:wrap;gap:7px;align-items:center;font-size:13px;color:var(--ink-muted)") },
      h("a", { href: "/", style: link }, "No-Experience Jobs"),
      h("span", { "aria-hidden": "true" }, "›"),
      h("span", { style: s("color:var(--ink);font-weight:700") }, label),
      h("script", { type: "application/ld+json", dangerouslySetInnerHTML: { __html: JSON.stringify(this.breadcrumbSchema(label, path)) } }));
  }

  // ── logo carousel (shared component; uses this page's H2 style) ──
  renderCarousel(){ return logoCarousel(this.data.brands || [], sectionH2); }

  // ── contact form (Name req, Email req, Organization, Message req; hidden source_page) ──
  renderContactForm(){
    const field = (label, required, node) => h("label", { style: s("display:grid;gap:6px") },
      h("span", { style: s("font-size:12.5px;font-weight:700;letter-spacing:0.02em;color:var(--ink-muted)") },
        label, required ? h("span", { style: s("color:var(--accent)") }, " *") : null),
      node);
    if (this.state.phase === "done") {
      return h("div", { style: s(card + ";justify-items:center;text-align:center;padding:30px 24px;gap:12px") },
        h("img", { src: "/logo.png", alt: "", width: 52, height: 52, style: s("width:52px;height:52px;object-fit:contain") }),
        h("div", { style: s("font-size:19px;font-weight:800;color:var(--ink)") }, "Thanks, we got it"),
        h("div", { style: s("font-size:15px;line-height:1.6;color:var(--ink-muted);text-wrap:pretty") }, "We read every message and will get back to you."));
    }
    const sending = this.state.phase === "sending";
    return h("form", { onSubmit: (e) => { e.preventDefault(); this.submit(); }, style: s(card) },
      h("input", { type: "hidden", name: "source_page", value: this.page }),
      field("Name", true, h("input", { type: "text", value: this.state.name, onChange: this.set("name"), className: "fc-bd-accent", autoComplete: "name", disabled: sending, style: s(inputStyle) })),
      field("Email", true, h("input", { type: "email", value: this.state.email, onChange: this.set("email"), className: "fc-bd-accent", autoComplete: "email", placeholder: "you@example.com", disabled: sending, style: s(inputStyle) })),
      field("Organization", false, h("input", { type: "text", value: this.state.organization, onChange: this.set("organization"), className: "fc-bd-accent", autoComplete: "organization", disabled: sending, style: s(inputStyle) })),
      field("Message", true, h("textarea", { value: this.state.message, onChange: this.set("message"), className: "fc-bd-accent", disabled: sending, style: s(areaStyle) })),
      this.state.error ? h("div", { role: "alert", style: s("font-size:14px;font-weight:600;color:var(--accent)") }, this.state.error) : null,
      h("button", { type: "submit", disabled: sending, style: s(cta + ";cursor:" + (sending ? "default" : "pointer")) },
        sending ? h("span", { "aria-hidden": "true", style: s("width:20px;height:20px;border:3px solid rgba(255,255,255,0.4);border-top-color:var(--accent-ink);border-radius:50%;animation:spin 0.8s linear infinite") }) : null,
        sending ? "Sending…" : "Send message"));
  }

  h2(text){ return h("h2", { style: s(sectionH2) }, text); }
  para(text){ return h("p", { style: s(PARA) }, text); }
  bullet(node){ return h("li", { style: s("display:flex;gap:10px;align-items:flex-start;font-size:16px;line-height:1.5;color:var(--ink)") },
    h("span", { "aria-hidden": "true", style: s("flex:none;margin-top:9px;width:6px;height:6px;border-radius:50%;background:var(--accent)") }),
    h("div", { style: s("min-width:0") }, node)); }

  renderAboutHero(){
    return h("section", { style: s("flex:none;background:linear-gradient(180deg,var(--fact) 0%,var(--surface) 60%);border-bottom:2px solid var(--ink)") },
      h("div", { style: s("max-width:" + RAIL + ";margin:0 auto;box-sizing:border-box;padding:22px 16px 30px;display:grid;gap:14px;align-content:start") },
        this.renderBreadcrumb("About", "/about/"),
        h("h1", { style: s(H1) }, "About Us")));
  }

  renderAbout(){
    return [
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("Why NoProbJobs exists"),
        this.para("Too many people get passed over for one reason: not enough experience. Hiring teams see it every day. Candidates with real drive and ability get screened out before they ever get a chance to show what they can do."),
        this.para("Job seekers feel it from the other side. A job title sounds like a great fit, then the requirements say otherwise. So they skip it and keep searching. Hours go by, and in the end they only feel confident applying to a handful of jobs, even when the real work lines up with what they can do."),
        this.para("NoProbJobs was built to change that. We believe in the human element of hiring, and that everyone, no matter their background, deserves free and fair access to opportunity."),
        h("p", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:18px;color:var(--ink)") }, "People want to work. Finding work should be easier.")),
      h("section", { style: s("display:grid;gap:14px") },
        this.h2("Meet the founder"),
        h("div", { style: s("display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap") },
          h("img", { src: "/logos/aboutusimage.png", alt: "Ryaire Richardson, Founder of NoProbJobs", width: 96, height: 96,
            style: s("width:96px;height:96px;border-radius:14px;object-fit:cover;flex:none;box-shadow:0 8px 24px rgba(10,58,117,0.16)") }),
          h("div", { style: s("display:grid;gap:6px;min-width:220px;flex:1") },
            h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:18px;color:var(--ink)") }, "Ryaire Richardson, Founder"),
            this.para("Seattle-based with roots in the Bay Area. 20+ years in tech, leading partnerships and business development. University of Washington, undergrad and MBA.")))),
      this.renderCarousel(),
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("Employers and partners"),
        this.para("Hiring for roles where the right attitude matters more than a resume? Working with job seekers who need a place to start? Let's talk."),
        this.renderContactForm()),
    ];
  }

  renderPartnersHero(){
    return h("section", { style: s("flex:none;background:linear-gradient(180deg,var(--fact) 0%,var(--surface) 60%);border-bottom:2px solid var(--ink)") },
      h("div", { style: s("max-width:" + RAIL + ";margin:0 auto;box-sizing:border-box;padding:22px 16px 30px;display:grid;gap:16px;align-content:start") },
        this.renderBreadcrumb("Partners", "/partners/"),
        h("h1", { style: s(H1) }, "Partner With NoProbJobs"),
        h("p", { style: s(PARA + ";max-width:52ch") }, "We help people find jobs that don't require experience. If you work with job seekers, we'd like to be a free tool you can hand them.")));
  }

  renderPartners(){
    return [
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("Who this is for"),
        this.para("Workforce centers, nonprofits, schools, libraries, and community programs that help people find work.")),
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("What job seekers get"),
        h("ul", { style: s("list-style:none;margin:0;padding:0;display:grid;gap:10px") },
          this.bullet("2,500+ jobs where the employer says no experience is needed, or that they'll train you"),
          this.bullet("Jobs straight from employer career sites, with direct apply links"),
          this.bullet("Posted dates on every job"),
          this.bullet(h("a", { href: ALERTS_HUB, style: s(LINK) }, "Free job alerts by work type")))),
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("How we Partner"),
        h("ul", { style: s("list-style:none;margin:0;padding:0;display:grid;gap:10px") },
          this.bullet("List NoProbJobs as a free resource for the people you serve"),
          this.bullet("Import NoProbJobs listings into your own job board via API"),
          this.bullet("Custom employer or job-type sourcing on request"))),
      this.renderCarousel(),
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("Let's talk"),
        this.renderContactForm()),
    ];
  }

  render(){
    const isAbout = this.page === "about";
    const sections = isAbout ? this.renderAbout() : this.renderPartners();
    const main = h("main", { style: s("flex:1;max-width:" + RAIL + ";width:100%;margin:0 auto;box-sizing:border-box;padding:32px 16px 44px;display:grid;gap:34px;align-content:start") },
      ...sections);
    return h("div", { className: "landing-scope", style: s("position:relative;display:flex;flex-direction:column;min-height:100%;background:var(--surface)") },
      h(Header, { productName: PRODUCT, alertsInHeader: false }),
      isAbout ? this.renderAboutHero() : this.renderPartnersHero(),
      main,
      siteFooter("washington"));
  }
}

const mount = (page, data) => {
  window.ReactDOM.createRoot(document.getElementById("root")).render(h(PagesApp, { page, data }));
};

const boot = () => {
  let page = "about", data = {};
  try { if ((window.location.pathname || "").indexOf("/partners") === 0) page = "partners"; } catch (e) {}
  const el = document.getElementById("__npj_data");
  if (el) {
    try {
      const d = JSON.parse(el.textContent);
      if (d.page === "about" || d.page === "partners") page = d.page;
      data = d;
    } catch (e) { /* fall back to path-derived page + empty data */ }
  }
  mount(page, data);
};
boot();
