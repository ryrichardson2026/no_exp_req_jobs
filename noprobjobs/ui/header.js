/* The one header. Both pages import this — no more hand-matched copies. Navy bar,
   marigold wordmark text (no block), tagline stacked beneath in newsprint, surface
   button with ink text. Responsive: the inner rail centres at 1120 and fills with
   padding below that. */
import { h, s } from "./h.js";

export function Header({ productName = "NoProbJobs.com", onAlerts, wide = false }){
  return h("header", { style: s("flex:none;background:var(--ink)") },
    h("div", { style: s("max-width:var(--rail,1120px);margin:0 auto;min-height:" + (wide ? "56px" : "46px") + ";display:flex;align-items:center;justify-content:space-between;gap:" + (wide ? "16px" : "9px") + ";padding:" + (wide ? "8px 14px" : "4px 12px")) },
      // The brand lockup is a link to the root landing (/), from any page — NOT the current
      // sub-page (e.g. /washington-jobs). text-decoration:none + hv-underline-none keep it
      // looking like a logo, not a text link; the inner spans keep their own colours.
      h("a", { href: "/", "aria-label": productName + " home", className: "hv-underline-none",
          style: s("display:flex;align-items:center;gap:" + (wide ? "12px" : "9px") + ";min-width:0;text-decoration:none") },
        // Logo slot — the NoProbJobs mark, left of the wordmark. Circle-clipped PNG on a
        // transparent ground (built by prerender/assets.mjs), so the yellow disc reads on
        // the navy bar. Shown on both mobile (34px) and desktop (40px); fixed box, so no
        // layout shift. alt="" — the wordmark beside it already names the brand. (B4/#3)
        h("img", { key: "logo", src: "/logo.png", alt: "", width: wide ? 40 : 26, height: wide ? 40 : 26,
          style: s("flex:none;object-fit:contain;width:" + (wide ? "40px" : "26px") + ";height:" + (wide ? "40px" : "26px")) }),
        h("div", { style: s("display:flex;flex-direction:column;gap:2px;min-width:0") },
          h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:17px;letter-spacing:-0.005em;white-space:nowrap;color:var(--mark)") }, productName),
          h("div", { style: s("font-size:" + (wide ? "13px" : "12px") + ";line-height:1.35;color:var(--surface);white-space:nowrap") }, "No experience? No problem.")
        )
      ),
      // Change #3: the job-alert CTA is marigold (the "this is us" mark colour), not white.
      // Label stays navy (--mark-ink === --ink): navy-on-marigold clears WCAG AA comfortably.
      // Hover/focus/active live in styles.css (.alert-cta) using existing tokens/filters only.
      h("button", { type: "button", onClick: onAlerts, "aria-haspopup": "dialog", className: "alert-cta",
        style: s("flex:none;min-height:44px;display:inline-flex;align-items:center;padding:" + (wide ? "0 16px" : "0 10px") + ";border:0;border-radius:3px;font-size:" + (wide ? "13.5px" : "12.5px") + ";font-weight:700;letter-spacing:" + (wide ? "0.04em" : "0.02em") + ";text-transform:uppercase;color:var(--mark-ink);background:var(--mark);cursor:pointer") },
        "Get job alerts")
    )
  );
}
