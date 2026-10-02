/* Shared site footer for the guide pages (alerts.js), the market index hub, and the static
   About/Partners pages. Extracted here so a footer change (e.g. the About/Partners links) lands
   on every one of those surfaces from a single definition. Market-aware: the "... job guides"
   link points at the current page's market index (marketIndexPath); pass null to omit it. */
import { h, s } from "./h.js";
import * as RT from "../data/routes.js";
import { marketBySlug, marketIndexPath } from "../data/alertPages.js";

const RAIL = "760px";
const footerLink = "min-height:44px;display:inline-flex;align-items:center;font-size:13px;font-weight:600;color:var(--line)";

export function siteFooter(marketSlug){
  const mk = marketSlug ? marketBySlug(marketSlug) : null;
  return h("footer", { style: s("flex:none;background:var(--ink)") },
    h("div", { style: s("max-width:" + RAIL + ";margin:0 auto;box-sizing:border-box;padding:16px 14px;display:grid;justify-items:center;gap:8px") },
      h("div", { style: s("font-size:14px;font-weight:600;color:var(--line);text-align:center") }, "Free for job seekers. No signup required to apply."),
      h("div", { style: s("display:flex;flex-wrap:wrap;justify-content:center;gap:4px 20px") },
        marketSlug ? h("a", { key: "g", href: marketIndexPath(marketSlug), style: s(footerLink) }, (mk ? mk.name : "Washington") + " job guides") : null,
        h("a", { key: "about", href: "/about/", style: s(footerLink) }, "About"),
        h("a", { key: "partners", href: "/partners/", style: s(footerLink) }, "Partners"),
        h("a", { key: "employers", href: "/employers/", style: s(footerLink) }, "Employers"),
        h("a", { key: "p", href: RT.PRIVACY_URL, target: "_blank", rel: "noopener noreferrer", style: s(footerLink) }, "Privacy Policy"))));
}
