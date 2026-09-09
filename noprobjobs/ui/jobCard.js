/* Job card. Shared by the board list and the landing "Recent jobs" grid. Renders a
   record already shaped into card props (company, cardTitle, locationLine, pay, posted,
   exp*, logo/monogram, href, onCardClick) — no record logic here.

   The clickable region is a real <a href> so crawlers can follow browse -> job (the
   internal-linking / authority path) and right-click-open works; on the board, onCardClick
   preventDefault()s and opens the panel instead, so in-app behaviour is unchanged. When a
   `listMeta` prop is passed (browse pages), the card is an ItemList ListItem carrying its
   rendered position and canonical URL — structured data about the LIST, not the job. */
import { h, s, raw } from "./h.js";

const OK_ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="var(--ok-ink-text)" stroke-width="1.8" style="flex:none" aria-hidden="true"><circle cx="8" cy="8" r="6.6"></circle><path d="M5 8.3l2.1 2.1L11 6.1"></path></svg>';
const STAR_ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="var(--fact-ink)" stroke-width="1.8" style="flex:none" aria-hidden="true"><path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .74 4.3L8 11.5l-3.84 2.1.74-4.3-3.1-3 4.3-.6z"></path></svg>';

export function JobCard({ job, flush, listMeta }){
  const outer = { role: "listitem", className: "hv-bg-sunk",
    style: s("position:relative;background:var(--surface-raised)" + (flush ? "" : ";border-bottom:1px solid var(--line)")) };
  if (listMeta) { outer.itemProp = "itemListElement"; outer.itemScope = true; outer.itemType = "https://schema.org/ListItem"; }
  return h("div", outer,
    listMeta && h("meta", { key: "pos", itemProp: "position", content: String(listMeta.position) }),
    listMeta && h("meta", { key: "url", itemProp: "url", content: listMeta.url }),
    job.isSelected && h("span", { key: "sel", "aria-hidden": "true",
      style: s("position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)") }),
    h("a", { href: job.href, onClick: job.onCardClick,
        style: s("padding:13px 16px 14px;display:grid;gap:4px;cursor:pointer;text-decoration:none;color:inherit") },
      h("div", { style: s("display:flex;align-items:center;gap:8px") },
        job.showLogo && h("span", { key: "lg", style: s("display:flex;flex:none") }, job.logoImg),
        job.showMonogram && h("span", { key: "mo", "aria-hidden": "true",
          style: s("width:20px;height:20px;display:grid;place-items:center;border-radius:3px;background:var(--fact);color:var(--fact-ink);font-size:12px;font-weight:800;flex:none") }, job.monogram),
        h("span", { style: s("font-size:13px;font-weight:500;color:var(--ink-muted)") }, job.company)
      ),
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-size:20px;line-height:1.2;font-weight:700;letter-spacing:-0.005em;color:var(--ink);text-wrap:pretty") }, job.cardTitle),
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
