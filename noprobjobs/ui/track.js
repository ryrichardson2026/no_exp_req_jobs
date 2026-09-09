/* GTM dataLayer push helper (change #5). Job cards and apply links are regenerated on
   every filter/refresh, so DOM-selector triggers in GTM are unreliable; the app pushes
   explicit named events instead. source_page is the route path so / and /washington[-jobs]
   and the board are separable in reporting. GTM is loaded through the static loader in each
   entry HTML (index.html / board.html); dataLayer exists by the time any handler fires, and
   the push is a no-op-safe array push if GTM hasn't loaded yet. */
export function sourcePage(){
  try { return window.location.pathname || "/"; } catch (e) { return "/"; }
}
export function track(event){
  try { (window.dataLayer = window.dataLayer || []).push(event); } catch (e) {}
}
