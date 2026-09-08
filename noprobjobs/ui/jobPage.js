/* Job detail. One component, two placements: a permanent panel on wide screens
   (isPermanent) and a full page reached by tapping a card on narrow ones
   (isMobilePage). `page` is a shaped record; `page.description` is a ready React
   element from data/describe.js. No record logic here. */
import { h, s, raw } from "./h.js";
import { Pressable } from "./pressable.js";

/* Primary-CTA bevel (C1): 3px bevel derived from --accent's own fill, no radius; on
   press the bevel inverts and the label shifts 1px. A press state is not a loading
   state — Apply opens the external ATS in a new tab after the press has ended. */
const CTA_BEVEL = (pd) => "border:0;background:var(--accent);color:var(--accent-ink);text-decoration:none;transition:box-shadow 40ms ease-out,transform 40ms ease-out;box-shadow:"
  + (pd ? "inset -3px -3px 0 0 var(--accent-lite),inset 3px 3px 0 0 var(--accent-dark);transform:translate(1px,1px)"
        : "inset 3px 3px 0 0 var(--accent-lite),inset -3px -3px 0 0 var(--accent-dark)");

const BACK_ICON = '<svg width="9" height="15" viewBox="0 0 9 15" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7.5 1.5 2 7.5l5.5 6"></path></svg>';
const CLOSE_ICON = '<svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M1.6 1.6l11.8 11.8"></path><path d="M13.4 1.6L1.6 13.4"></path></svg>';
const OK_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" style="flex:none" aria-hidden="true"><circle cx="8" cy="8" r="6.6"></circle><path d="M5 8.3l2.1 2.1L11 6.1"></path></svg>';
const STAR_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="1.8" style="flex:none;margin-top:2px" aria-hidden="true"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .74 4.3L8 11.5l-3.84 2.1.74-4.3-3.1-3 4.3-.6z"></path></svg>';
const INFO_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" style="flex:none;margin-top:3px;color:var(--fact-ink)" aria-hidden="true"><circle cx="8" cy="8" r="6.6"></circle><path d="M8 7.2v4"></path><path d="M8 4.8v.1"></path></svg>';
const TYPE_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--fact-ink)" stroke-width="1.7" style="flex:none" aria-hidden="true"><rect x="2.2" y="5.3" width="11.6" height="8.2" rx="1.3"></rect><path d="M6 5.3V3.7h4v1.6"></path></svg>';
const SHIFT_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--fact-ink)" stroke-width="1.7" style="flex:none" aria-hidden="true"><path d="M12.7 9.9A5.3 5.3 0 0 1 6.1 3.3a5.4 5.4 0 1 0 6.6 6.6z"></path></svg>';
const FTE_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--fact-ink)" stroke-width="1.7" style="flex:none" aria-hidden="true"><circle cx="8" cy="8" r="6.6"></circle><path d="M8 8V2.6"></path><path d="M8 8h5.4"></path></svg>';
const CLOCK_ICON = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" style="flex:none" aria-hidden="true"><circle cx="8" cy="8" r="6.6"></circle><path d="M8 4.6v3.7l2.5 1.4"></path></svg>';

function modIcon(m){
  if (m.isType) return raw(TYPE_ICON);
  if (m.isShift) return raw(SHIFT_ICON);
  if (m.isFte) return raw(FTE_ICON);
  return null;
}

export function JobPage({ page, categories = [], back, isMobilePage = false, isPanel = false, isPermanent = false }){
  const applyBtn = (key) => h(Pressable, { key, tag: "a", href: page.applyUrl, target: "_blank", rel: "noopener noreferrer", className: "hv-bright",
    styleFor: (pd) => s("margin-top:14px;justify-self:center;min-height:44px;display:inline-flex;align-items:center;justify-content:center;padding:0 24px;font-size:15.5px;font-weight:700;" + CTA_BEVEL(pd)) }, "Apply on employer site");

  return h("div", { style: s("height:100%;display:flex;flex-direction:column;min-height:0;background:var(--surface-raised)") },
    // Top bar — rendered ONLY when it carries a control: the mobile back button or
    // the panel close button. In the permanent desktop panel neither renders, so the
    // bar is omitted entirely rather than left as an empty bordered band above the
    // title (the "unknown gap above the job detail" — Phase B, B2).
    (isMobilePage || isPanel) && h("div", { style: s("flex:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 6px 6px 4px;border-bottom:1px solid var(--line)") },
      isMobilePage && h("button", { key: "bk", type: "button", onClick: back,
          style: s("min-height:44px;display:flex;align-items:center;gap:6px;padding:0 12px;background:transparent;border:0;font-size:15px;font-weight:600;color:var(--ink);cursor:pointer") },
        raw(BACK_ICON), h("span", null, "Jobs")),
      isPanel && h("button", { key: "cl", type: "button", onClick: back, "aria-label": "Close job", className: "hv-tx-accent",
          style: s("width:44px;height:44px;display:grid;place-items:center;background:transparent;border:0;cursor:pointer;color:var(--ink)") },
        raw(CLOSE_ICON))
    ),
    // scroll body
    h("div", { style: s("flex:1;min-height:0;overflow-y:auto") },
      h("div", { style: s("padding:16px 20px 20px;display:grid;gap:5px;border-bottom:1px solid var(--line)") },
        h("h1", { style: s("margin:0;font-family:var(--font-display);font-size:27px;line-height:1.14;font-weight:800;letter-spacing:-0.008em;color:var(--ink);text-wrap:pretty") }, page.title),
        h("div", { style: s("display:flex;align-items:center;gap:9px;margin-top:1px") },
          page.showLogo && h("span", { key: "lg", style: s("display:flex;flex:none") }, page.pageLogoImg),
          page.showMonogram && h("span", { key: "mo", "aria-hidden": "true",
            style: s("width:24px;height:24px;display:grid;place-items:center;border-radius:3px;background:var(--fact);color:var(--fact-ink);font-size:13px;font-weight:800;flex:none") }, page.monogram),
          h("span", { style: s("font-size:16px;font-weight:600;color:var(--ink)") }, page.company)
        ),
        h("div", { style: s("font-size:15px;color:var(--ink-muted)") }, page.locationLine),
        page.pay && h("div", { key: "pay", style: s("font-size:17px;font-weight:700;color:var(--ink);margin-top:3px") }, page.pay),

        page.expired && h("div", { key: "exp", style: s("margin-top:12px;padding:14px;background:var(--surface-sunk);display:grid;gap:4px") },
          h("div", { style: s("font-size:15px;font-weight:700;color:var(--ink)") }, "This job is no longer accepting applications."),
          h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") }, "The employer removed the posting. Browse other retail jobs below.")
        ),
        page.expired && h("div", { key: "exc", style: s("margin-top:12px;display:flex;flex-wrap:wrap;gap:8px") },
          categories.map((cat) => h("button", { key: cat, type: "button", className: "hv-bd-accent-tx",
            style: s("min-height:44px;padding:0 14px;border-radius:3px;background:var(--surface-raised);border:1px solid var(--line);font-size:15px;font-weight:500;color:var(--ink);cursor:pointer") }, cat))
        ),

        page.live && applyBtn("apply-top")
      ),

      page.hasModifiers && h("div", { key: "mods", style: s("margin:14px 20px;padding:12px 14px;background:var(--surface-raised);border:2px solid var(--line);border-radius:3px;display:grid;gap:8px") },
        page.expStrong && h("div", { key: "es", style: s("display:flex;align-items:flex-start;gap:9px;color:var(--ok-ink-text)") },
          raw(OK_ICON), h("span", { style: s("font-size:16px;font-weight:700") }, page.expLabel)),
        page.verbatimNeedsLabel && h("div", { key: "vn", style: s("display:flex;align-items:flex-start;gap:9px") },
          raw(STAR_ICON),
          h("div", { style: s("display:grid;gap:2px") },
            h("div", { style: s("font-size:16px;font-weight:700;color:var(--accent)") }, page.expLabel),
            h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") }, "“" + page.expVerbatim + "”")
          )
        ),
        page.verbatimBare && h("div", { key: "vb", style: s("display:flex;align-items:flex-start;gap:9px") },
          raw(INFO_ICON),
          h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") }, "“" + page.expVerbatim + "”")
        ),
        (page.modifiers || []).map((m, i) => h("div", { key: "m" + i, style: s("display:flex;align-items:center;gap:9px;font-size:15px;font-weight:600;color:var(--ink)") },
          modIcon(m), h("span", null, m.value))),
        page.posted && h("div", { key: "po", style: s("display:flex;align-items:center;gap:9px;font-size:15px;color:var(--ink-muted)") },
          raw(CLOCK_ICON), h("span", null, page.posted))
      ),

      h("div", { style: s("padding:20px 20px 8px") },
        h("div", { "data-desc-html": "true" }, page.description)
      ),

      page.live && h("div", { key: "apply-btm", style: s("padding:8px 20px 28px;display:grid;gap:8px;justify-items:center") },
        h(Pressable, { tag: "a", href: page.applyUrl, target: "_blank", rel: "noopener noreferrer", className: "hv-bright",
          styleFor: (pd) => s("min-height:44px;display:inline-flex;align-items:center;justify-content:center;padding:0 24px;font-size:15.5px;font-weight:700;" + CTA_BEVEL(pd)) }, "Apply on employer site"),
        h("div", { style: s("font-size:13px;line-height:1.45;color:var(--ink-muted);text-align:center") }, "Job posting managed by employer")
      )
    )
  );
}
