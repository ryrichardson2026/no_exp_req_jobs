/* The one header. Both pages import this — no more hand-matched copies. Navy bar,
   marigold wordmark text (no block), tagline stacked beneath in newsprint, surface
   button with ink text. Responsive: the inner rail centres at 1120 and fills with
   padding below that. */
import { h, s } from "./h.js";

export function Header({ productName = "NoProbJobs.com", onAlerts, wide = false }){
  return h("header", { style: s("flex:none;background:var(--ink)") },
    h("div", { style: s("max-width:1120px;margin:0 auto;min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 14px") },
      h("div", { style: s("display:flex;align-items:center;gap:12px;min-width:0") },
        // Logo slot — fixed square left of the wordmark, using the job-card monogram
        // fallback (--fact ground, --fact-ink letterform, 3px corners). Placeholder mark
        // now, takes an image later with no layout shift. Desktop only (gated on `wide`):
        // the mobile header is already tight. Does not stretch the wordmark. (B4/#3)
        wide && h("span", { key: "logo", "aria-hidden": "true",
          style: s("flex:none;width:40px;height:40px;display:grid;place-items:center;border-radius:3px;background:var(--fact);color:var(--fact-ink);font-family:var(--font-display);font-size:22px;font-weight:800;line-height:1") }, "N"),
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
