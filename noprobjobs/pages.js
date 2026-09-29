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

// horizontal auto-scrolling logo strip; pauses on hover, and stops + wraps under reduced-motion.
const CAROUSEL_CSS =
  "@keyframes npj-marq{from{transform:translateX(0)}to{transform:translateX(-50%)}}"
  + ".npj-marquee{overflow:hidden;position:relative;-webkit-mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent);mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent)}"
  + ".npj-marquee-track{display:flex;align-items:center;gap:34px;width:max-content;animation:npj-marq 55s linear infinite}"
  + ".npj-marquee:hover .npj-marquee-track{animation-play-state:paused}"
  + "@media(prefers-reduced-motion:reduce){.npj-marquee-track{animation:none;flex-wrap:wrap;width:auto;justify-content:center;gap:18px 30px}}";

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

  // ── logo carousel ──
  renderCarousel(){
    const brands = this.data.brands || [];
    if (!brands.length) return null;
    const logo = (b, i) => h("div", { key: i, style: s("flex:none;display:flex;align-items:center;justify-content:center;height:46px") },
      h("img", { src: "/logos/" + b.file, alt: b.name, height: 36, loading: "lazy",
        style: s("height:36px;max-width:132px;width:auto;object-fit:contain;display:block") }));
    const loop = brands.concat(brands).map(logo);   // two copies -> seamless -50% loop
    return h("section", { style: s("display:grid;gap:16px") },
      h("h2", { style: s(sectionH2) }, "See jobs from employers like:"),
      h("style", { dangerouslySetInnerHTML: { __html: CAROUSEL_CSS } }),
      h("div", { className: "npj-marquee" },
        h("div", { className: "npj-marquee-track" }, loop)));
  }

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
      h("div", { style: s("max-width:" + RAIL + ";margin:0 auto;box-sizing:border-box;padding:22px 16px 30px;display:grid;gap:18px;align-content:start") },
        this.renderBreadcrumb("About", "/about/"),
        h("h1", { style: s(H1) }, "About NoProbJobs"),
        h("div", { style: s("display:flex;gap:16px;align-items:center;flex-wrap:wrap") },
          h("img", { src: "/logos/aboutusimage.png", alt: "Ryaire Richardson, Founder of NoProbJobs", width: 92, height: 92,
            style: s("width:92px;height:92px;border-radius:14px;object-fit:cover;flex:none;box-shadow:0 8px 24px rgba(10,58,117,0.16)") }),
          h("div", { style: s("display:grid;gap:2px") },
            h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:20px;color:var(--ink)") }, "Ryaire Richardson"),
            h("div", { style: s("font-size:15px;color:var(--ink-muted)") }, "Founder, NoProbJobs"))),
        this.para("20+ years in tech, leading partnerships and business development. University of Washington graduate, Seattle-based.")));
  }

  renderAbout(){
    return [
      this.para("I believe in the human element of hiring, and in leveling the playing field so everyone, no matter their background, has free and fair access to opportunity."),
      this.para("As a tech leader, I see hundreds of resumes a month. Many get turned down for one reason: not enough experience. That has always weighed on me. Some of those people had the drive and the ability to do great work. They just never got the chance to show it."),
      this.para("I've been on the other side too. I've searched for jobs, found titles that sounded like a great fit, then read the requirements and decided I wasn't qualified. So I skipped it and kept looking. Hours went by. By the end I'd only feel confident applying to a handful of jobs, even though the real work was often closer to my background than the posting made it sound."),
      h("p", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:18px;color:var(--ink)") }, "That's why I built NoProbJobs."),
      h("section", { style: s("display:grid;gap:12px") },
        this.h2("What we do differently"),
        this.para("Every job on NoProbJobs is checked for experience requirements. If a job asks for experience, it doesn't make the list. What's left are jobs where the employer says no experience is needed, or that they'll train you."),
        h("ul", { style: s("list-style:none;margin:0;padding:0;display:grid;gap:10px") },
          this.bullet("2,500+ jobs checked, straight from employer career sites"),
          this.bullet("Apply links go directly to the employer"),
          this.bullet("Every listing shows when it was posted")),
        this.para("The goal is simple: less time reading requirements you don't meet, more time applying to jobs you can actually get."),
        this.para("People want to work. Finding work should be easier."),
        h("a", { href: ALERTS_HUB, style: s(LINK + ";font-size:16px") }, "Get free job alerts for the work you want.")),
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
        this.h2("How partners can help"),
        h("ul", { style: s("list-style:none;margin:0;padding:0;display:grid;gap:10px") },
          this.bullet("List NoProbJobs as a job seeker resource"),
          this.bullet(["Share our ", h("a", { key: "l", href: ALERTS_HUB, style: s(LINK) }, "job alert pages"), " with the people you serve"]),
          this.bullet("Tell us what your job seekers are looking for, so we can add more of it"))),
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
