/* Share a job. One function used by the card share icon and the job page "Apply later"
   button. On mobile (navigator.share) it opens the native share sheet; on desktop it copies
   the link and shows a brief "Link copied" confirmation. NOTHING is saved to a profile — the
   user is just sending the job to themselves or someone else. Fires a GA4 share_click via the
   same dataLayer helper apply_click uses (ui/track.js); apply_click is untouched. */
import { track, sourcePage } from "./track.js";

const ORIGIN = "https://noprobjobs.com";

/* Universal share glyph (square tray + up arrow). stroke=currentColor so the caller sets the
   color; rendered via raw(). Modest ~18px. */
export const SHARE_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15.5V3"></path><path d="M7.5 7L12 2.5 16.5 7"></path><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"></path></svg>';

/* Absolute canonical job URL (/jobs/{slug}-{number}/) + ?utm_source=share. `path` is the job's
   own canonical path (never the board/listing URL). Falls back to the current location on a
   standalone job page. */
export function jobShareUrl(path){
  let u = path || (typeof window !== "undefined" ? window.location.pathname : "/");
  if (u.indexOf("http") !== 0) u = ORIGIN + (u.charAt(0) === "/" ? u : "/" + u);
  u = u.split("#")[0];
  return u + (u.indexOf("?") >= 0 ? "&" : "?") + "utm_source=share";
}

function copyText(text){
  try { if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text); } catch (e) {}
  // file://-safe fallback (same technique as the dashboard copy buttons): hidden textarea + execCommand.
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.top = "-1000px"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      const ok = document.execCommand("copy"); document.body.removeChild(ta);
      ok ? resolve() : reject(new Error("execCommand copy failed"));
    } catch (e) { reject(e); }
  });
}

/* Minimal self-contained toast (no board state plumbing). role=status for a11y; fades out. */
function toast(msg){
  try {
    const el = document.createElement("div");
    el.setAttribute("role", "status");
    el.textContent = msg;
    el.style.cssText = "position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:9999;"
      + "background:var(--ink,#0b0b0b);color:var(--accent-ink,#fff);font-size:15px;font-weight:600;"
      + "padding:11px 18px;border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.26);opacity:0;transition:opacity .18s ease-out";
    document.body.appendChild(el);
    requestAnimationFrame(() => { el.style.opacity = "1"; });
    setTimeout(() => { el.style.opacity = "0"; setTimeout(() => { try { document.body.removeChild(el); } catch (e) {} }, 240); }, 1700);
  } catch (e) {}
}

/* shareLocation = "card" | "job_page". evt = optional extra GA4 params (job_id, employer),
   merged exactly like apply_click merges page.applyEvt. */
export function shareJob({ url, title, shareLocation, evt }){
  track(Object.assign({ event: "share_click", source_page: sourcePage(), share_location: shareLocation }, evt || {}));
  try {
    if (typeof navigator !== "undefined" && navigator.share) {
      navigator.share({ title: title, url: url }).catch(() => {});   // silently ignore user cancel
      return;
    }
  } catch (e) {}
  copyText(url).then(() => toast("Link copied")).catch(() => toast("Couldn’t copy the link"));
}
