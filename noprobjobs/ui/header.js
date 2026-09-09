/* The one header. Both pages import this — no more hand-matched copies. Navy bar,
   marigold wordmark text (no block), tagline stacked beneath in newsprint, surface
   button with ink text. Responsive: the inner rail centres at 1120 and fills with
   padding below that. */
import { h, s } from "./h.js";

export function Header({ productName = "NoProbJobs.com", onAlerts, wide = false }){
  return h("header", { style: s("flex:none;background:var(--ink)") },
    h("div", { style: s("max-width:1120px;margin:0 auto;min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 14px") },
      h("div", { style: s("display:flex;align-items:center;gap:12px;min-width:0") },
        // Logo slot — the NoProbJobs mark, left of the wordmark. Circle-clipped PNG on a
        // transparent ground (built by prerender/assets.mjs), so the yellow disc reads on
        // the navy bar. Shown on both mobile (34px) and desktop (40px); fixed box, so no
        // layout shift. alt="" — the wordmark beside it already names the brand. (B4/#3)
        h("img", { key: "logo", src: "/logo.png", alt: "", width: wide ? 40 : 34, height: wide ? 40 : 34,
          style: s("flex:none;object-fit:contain;width:" + (wide ? "40px" : "34px") + ";height:" + (wide ? "40px" : "34px")) }),
        h("div", { style: s("display:flex;flex-direction:column;gap:2px;min-width:0") },
          h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:17px;letter-spacing:-0.005em;white-space:nowrap;color:var(--mark)") }, productName),
          h("div", { style: s("font-size:13px;line-height:1.35;color:var(--surface);white-space:nowrap") }, "No experience? No problem.")
        )
      ),
      h("button", { type: "button", onClick: onAlerts, "aria-haspopup": "dialog",
        style: s("flex:none;min-height:44px;display:inline-flex;align-items:center;padding:0 16px;border:0;border-radius:3px;font-size:13.5px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:var(--ink);background:var(--surface);cursor:pointer") },
        "Get job alerts")
    )
  );
}
