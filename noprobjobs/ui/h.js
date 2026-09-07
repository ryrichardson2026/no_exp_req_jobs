/* Render helpers. React itself is the vendored UMD global (window.React); this module
   only aliases createElement and turns the design's inline-style STRINGS into the
   style OBJECTS React wants — so every style="…" from the original .dc templates
   transfers verbatim as s("…"), no hand-conversion and no chance of drift. */
const React = window.React;
export const h = React.createElement.bind(React);
export const Fragment = React.Fragment;

function kebabToCamel(s){ return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }

/* Copied from the retired support.js cssToObj: split declarations, keep custom
   properties (--x) as-is, camel-case the rest. One first-colon split per decl. */
export function s(css){
  const o = {};
  for (const decl of String(css).split(";")) {
    const i = decl.indexOf(":");
    if (i < 0) continue;
    const prop = decl.slice(0, i).trim();
    if (!prop) continue;
    o[prop.startsWith("--") ? prop : kebabToCamel(prop)] = decl.slice(i + 1).trim();
  }
  return o;
}

/* Render a raw SVG (or other static) markup string verbatim. React's createElement
   would need every SVG attribute (stroke-width, viewBox, clip-rule…) rewritten to
   camelCase; instead the browser's HTML parser handles them unchanged. The wrapper is
   display:contents so it adds no box — the <svg>'s own flex:none / margins apply as if
   it were a direct child. Every icon is aria-hidden and decorative. */
export const raw = (markup) => h("span", { style: { display: "contents" }, dangerouslySetInnerHTML: { __html: markup } });
