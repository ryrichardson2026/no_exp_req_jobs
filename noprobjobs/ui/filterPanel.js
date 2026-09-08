/* Filter panel. Sections are switched on independently (isSort/isCat/isPay/isShift/
   isType/isLoc); the board shows one section per popover and all of them in the mobile
   drawer (with `divided` separators). Option arrays and handlers come from the board. */
import { h, s, raw } from "./h.js";

const SORT_CHECK = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="2" style="flex:none" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';
const CHECK14 = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" style="flex:none" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';

const sep = (k) => h("span", { key: k, style: s("height:1px;background:var(--line)") });

/* Category row — a real checkbox with the whole row as the hit target. Replaces the
   old bordered-button grid so Type of work reads as a multi-select list, matching the
   mobile sheet, and pairs with the popover's Apply footer (B1). Fixed order, no counts. */
function catRow(opt, i){
  const on = opt.isOn;
  return h("button", { key: i, type: "button", role: "checkbox", "aria-checked": on, onClick: opt.pick, className: "hv-bg-sunk",
      style: s("width:100%;min-height:44px;display:flex;align-items:center;gap:11px;padding:0 8px;background:transparent;border:0;border-radius:3px;font-size:15px;color:var(--ink);cursor:pointer;text-align:left") },
    h("span", { "aria-hidden": "true",
        style: s("flex:none;width:20px;height:20px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (on ? "var(--ink)" : "var(--line)") + ";background:" + (on ? "var(--ink)" : "var(--surface)")) },
      on ? raw(CHECK14) : null),
    h("span", { style: s("flex:1;font-weight:" + (on ? "700" : "500")) }, opt.label));
}

/* On / off / unavailable pill — identical structure for shift and type. */
function pill(opt, i){
  if (opt.isOn) return h("span", { key: i, style: s("display:flex") },
    h("button", { type: "button", onClick: opt.pick, "aria-pressed": true,
        style: s("min-height:44px;display:flex;align-items:center;gap:7px;padding:0 14px;border-radius:3px;background:var(--ink);border:1px solid var(--ink);font-size:15px;font-weight:700;color:var(--accent-ink);cursor:pointer") },
      raw(CHECK14), h("span", null, opt.label)));
  if (opt.isOff) return h("span", { key: i, style: s("display:flex") },
    h("button", { type: "button", onClick: opt.pick, "aria-pressed": false, className: "hv-bd-accent-tx",
        style: s("min-height:44px;display:flex;align-items:center;padding:0 11px;border-radius:3px;background:var(--surface-raised);border:1px solid var(--line);font-size:15px;font-weight:500;color:var(--ink);cursor:pointer") },
      opt.label));
  return h("span", { key: i, style: s("display:flex") },
    h("button", { type: "button", disabled: true, "aria-disabled": true,
        style: s("min-height:44px;display:flex;align-items:center;padding:0 11px;border-radius:3px;background:var(--surface-raised);border:1px dashed var(--line);font-size:15px;font-weight:500;color:var(--ink-muted);opacity:0.55;cursor:not-allowed") },
      opt.label));
}

/* "Apply all" — a select-all checkbox (not a commit button): checks every option in the
   menu, or clears them if all are already on. Sits at the top of each multi-select menu. */
function applyAllRow(on, onClick){
  return h("button", { key: "all", type: "button", role: "checkbox", "aria-checked": on, onClick, className: "hv-bg-sunk",
      style: s("width:100%;min-height:44px;display:flex;align-items:center;gap:11px;padding:0 8px;background:transparent;border:0;font-size:15px;font-weight:700;color:var(--ink);cursor:pointer;text-align:left") },
    h("span", { "aria-hidden": "true",
        style: s("flex:none;width:20px;height:20px;display:grid;place-items:center;border-radius:3px;color:var(--accent-ink);border:1px solid " + (on ? "var(--ink)" : "var(--line)") + ";background:" + (on ? "var(--ink)" : "var(--surface)")) },
      on ? raw(CHECK14) : null),
    h("span", null, "Apply all"));
}

export function FilterPanel(p){
  const kids = [];

  if (p.isSort) kids.push(h("div", { key: "sort", style: s("display:grid;gap:8px") },
    h("div", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Sort"),
    h("div", { style: s("display:grid;gap:2px") },
      (p.sortOptions || []).map((so, i) => h("button", { key: i, type: "button", onClick: so.pick, "aria-pressed": so.isCurrent, className: "hv-bg-sunk",
          style: s("min-height:44px;display:flex;align-items:center;gap:8px;padding:0 8px;background:transparent;border:0;border-radius:3px;font-size:15px;color:var(--ink);cursor:pointer;text-align:left") },
        so.isCurrent
          ? [raw(SORT_CHECK), h("span", { key: "l", style: s("flex:1;font-weight:700;color:var(--accent)") }, so.label)]
          : [h("span", { key: "sp", "aria-hidden": "true", style: s("width:17px;flex:none") }), h("span", { key: "l", style: s("flex:1") }, so.label)]
      ))
    )
  ));

  if (p.divided) kids.push(sep("d1"));
  if (p.isCat) kids.push(h("div", { key: "cat", style: s("display:grid;gap:6px") },
    h("div", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Type of work"),
    h("div", { style: s("display:grid;gap:2px") },
      (p.catAll ? [applyAllRow(p.catAllOn, p.catAll)] : []).concat((p.catOptions || []).map((c, i) => catRow(c, i))))
  ));

  if (p.divided) kids.push(sep("d2"));
  if (p.isPay) kids.push(h("div", { key: "pay", style: s("display:grid;gap:10px") },
    h("div", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Pay"),
    p.showsPay
      ? h("button", { type: "button", onClick: p.togglePay, "aria-pressed": true,
          style: s("align-self:start;min-height:44px;display:flex;align-items:center;gap:8px;padding:0 14px;border-radius:3px;background:var(--ink);border:1px solid var(--ink);font-size:15px;font-weight:700;color:var(--accent-ink);cursor:pointer") },
        raw(CHECK14), h("span", null, "Shows pay"))
      : h("button", { type: "button", onClick: p.togglePay, "aria-pressed": false, className: "hv-bd-accent-tx",
          style: s("align-self:start;min-height:44px;display:flex;align-items:center;padding:0 11px;border-radius:3px;background:var(--surface-raised);border:1px solid var(--line);font-size:15px;font-weight:500;color:var(--ink);cursor:pointer") },
        "Shows pay"),
    h("div", { style: s("font-size:13px;line-height:1.45;color:var(--ink-muted);text-wrap:pretty") }, "Most employers don’t state pay. Turning this on narrows to the jobs that do.")
  ));

  if (p.divided) kids.push(sep("d3"));
  if (p.isShift) kids.push(h("div", { key: "shift", style: s("display:grid;gap:8px") },
    h("div", { style: s("display:grid;gap:3px") },
      h("div", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Shift"),
      h("div", { style: s("font-size:13px;line-height:1.45;color:var(--ink-muted);text-wrap:pretty") }, "Few employers state a shift. Turning one on narrows to the jobs that do.")
    ),
    p.shiftAll && applyAllRow(p.shiftAllOn, p.shiftAll),
    h("div", { style: s("display:flex;flex-wrap:wrap;gap:8px") }, (p.shiftOptions || []).map((so, i) => pill(so, i)))
  ));

  if (p.divided) kids.push(sep("d4"));
  if (p.isType) kids.push(h("div", { key: "type", style: s("display:grid;gap:8px") },
    h("div", { style: s("display:grid;gap:3px") },
      h("div", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Employment type"),
      h("div", { style: s("font-size:13px;line-height:1.45;color:var(--ink-muted);text-wrap:pretty") }, "Some employers don’t state a type. Turning one on narrows to the jobs that do.")
    ),
    p.typeAll && applyAllRow(p.typeAllOn, p.typeAll),
    h("div", { style: s("display:flex;flex-wrap:wrap;gap:8px") }, (p.typeOptions || []).map((t, i) => pill(t, i)))
  ));

  if (p.divided) kids.push(sep("d5"));
  if (p.isLoc) kids.push(h("div", { key: "loc", style: s("display:grid;gap:14px") },
    h("div", { style: s("display:flex;align-items:baseline;justify-content:space-between;gap:12px") },
      h("div", { style: s("font-size:13px;font-weight:700;letter-spacing:0.01em;color:var(--ink-muted)") }, "Location"),
      p.hasLoc && h("button", { key: "clr", type: "button", onClick: p.clearLoc,
        style: s("min-height:44px;margin:-6px 0;padding:0 6px;background:transparent;border:0;font-size:14px;font-weight:600;color:var(--accent);cursor:pointer") }, "Clear")
    ),
    h("div", { style: s("display:flex;gap:8px;align-items:stretch") },
      h("input", { type: "text", value: p.locDraft, onChange: p.onLocDraft, onKeyDown: p.onLocKey, placeholder: "City, state or ZIP", "aria-label": "City, state or ZIP", className: "fc-bd-accent",
        style: s("flex:1;min-width:0;box-sizing:border-box;min-height:48px;padding:0 12px;border:1px solid var(--line);border-radius:3px;background:var(--surface);font-size:16px;color:var(--ink)") }),
      h("button", { type: "button", onClick: p.applyDraft,
        style: s("flex:none;min-height:44px;padding:0 14px;border-radius:3px;background:var(--accent);border:1px solid var(--accent);font-size:15px;font-weight:700;color:var(--accent-ink);cursor:pointer") }, "Use")
    ),
    h("div", { style: s("display:grid;gap:6px") },
      h("div", { style: s("display:flex;gap:8px") }, (p.radiusOptions || []).map((r, i) => {
        if (r.isOff) return h("button", { key: i, type: "button", disabled: true, "aria-disabled": true,
          style: s("min-height:44px;flex:1;border-radius:3px;font-size:14px;font-weight:500;cursor:not-allowed;background:var(--surface-raised);border:1px dashed var(--line);color:var(--ink-muted);opacity:0.6") }, r.label);
        if (r.isOnCurrent) return h("button", { key: i, type: "button", onClick: r.pick, "aria-pressed": true,
          style: s("min-height:44px;flex:1;border-radius:3px;font-size:14px;font-weight:700;cursor:pointer;background:var(--ink);border:1px solid var(--ink);color:var(--accent-ink)") }, r.label);
        return h("button", { key: i, type: "button", onClick: r.pick, "aria-pressed": false, className: "hv-bd-accent",
          style: s("min-height:44px;flex:1;border-radius:3px;font-size:14px;font-weight:600;cursor:pointer;background:var(--surface-raised);border:1px solid var(--line);color:var(--ink)") }, r.label);
      })),
      p.radiusInactive && h("div", { key: "rn", style: s("font-size:12.5px;line-height:1.4;color:var(--ink-muted)") }, "Radius applies to a ZIP code. A city or state name filters to that area.")
    ),
    p.unmatched && h("div", { key: "um", style: s("font-size:15px;line-height:1.5;color:var(--ink);text-wrap:pretty") }, p.unmatchedLine),
    p.noCityMatch && h("div", { key: "nc", style: s("font-size:15px;line-height:1.5;color:var(--ink);text-wrap:pretty") }, p.noCityMatchLine)
  ));

  return h("div", { style: s("display:grid;gap:12px;padding:12px 12px 14px") }, kids);
}
