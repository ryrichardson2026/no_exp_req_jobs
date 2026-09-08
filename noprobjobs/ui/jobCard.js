/* Job card. Shared by the board list and the landing "Recent jobs" grid. Renders a
   record already shaped into card props (company, cardTitle, locationLine, pay,
   posted, exp*, logo/monogram, open handlers) — no record logic here. */
import { h, s, raw } from "./h.js";

const OK_ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="var(--ok-ink-text)" stroke-width="1.8" style="flex:none" aria-hidden="true"><circle cx="8" cy="8" r="6.6"></circle><path d="M5 8.3l2.1 2.1L11 6.1"></path></svg>';
const STAR_ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="var(--fact-ink)" stroke-width="1.8" style="flex:none" aria-hidden="true"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .74 4.3L8 11.5l-3.84 2.1.74-4.3-3.1-3 4.3-.6z"></path></svg>';

export function JobCard({ job, flush }){
  // flush: drop the list separator border-bottom. The board renders JobCard as a dense
  // bordered list (keeps it); the landing grid wraps each card in a floating,
  // offset-shadow container with its own all-around border, so the separator is dropped.
  return h("div", { role: "listitem", className: "hv-bg-sunk",
      style: s("position:relative;background:var(--surface-raised)" + (flush ? "" : ";border-bottom:1px solid var(--line)")) },
    job.isSelected && h("span", { key: "sel", "aria-hidden": "true",
      style: s("position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)") }),
    h("div", { tabIndex: 0, role: "link", onClick: job.open, onKeyDown: job.openKey,
        style: s("padding:13px 16px 14px;display:grid;gap:4px;cursor:pointer") },
      h("div", { style: s("display:flex;align-items:center;gap:8px") },
        job.showLogo && h("span", { key: "lg", style: s("display:flex;flex:none") }, job.logoImg),
        job.showMonogram && h("span", { key: "mo", "aria-hidden": "true",
          style: s("width:20px;height:20px;display:grid;place-items:center;border-radius:3px;background:var(--fact);color:var(--fact-ink);font-size:12px;font-weight:800;flex:none") }, job.monogram),
        h("span", { style: s("font-size:13px;font-weight:500;color:var(--ink-muted)") }, job.company)
      ),
      h("div", { style: s("font-family:var(--font-display);font-size:20px;line-height:1.2;font-weight:700;letter-spacing:-0.005em;color:var(--ink);text-wrap:pretty") }, job.cardTitle),
      h("div", { style: s("font-size:15px;line-height:1.35;color:var(--ink-muted)") }, job.locationLine),
      job.pay && h("div", { key: "pay", style: s("font-size:15px;line-height:1.35;font-weight:600;color:var(--ink)") }, job.pay),
      job.expStrong && h("div", { key: "es", style: s("display:inline-flex;align-items:center;gap:6px;margin-top:2px;padding:3px 7px;border-radius:3px;background:var(--ok-soft);justify-self:start") },
        raw(OK_ICON),
        h("span", { style: s("font-size:14px;font-weight:700;color:var(--ok-ink-text)") }, job.expLabel)
      ),
      job.expSoft && h("div", { key: "ef", style: s("display:inline-flex;align-items:center;gap:6px;margin-top:2px;padding:3px 7px;border-radius:3px;background:var(--fact);justify-self:start") },
        raw(STAR_ICON),
        h("span", { style: s("font-size:14px;font-weight:700;color:var(--fact-ink)") }, job.expLabel)
      ),
      job.posted && h("div", { key: "po", style: s("font-size:13px;color:var(--ink-muted);margin-top:2px") }, job.posted)
    )
  );
}
