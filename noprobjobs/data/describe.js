/* The description → rendered-markup pipeline, extracted verbatim from Job Board.dc.html
   so the shared Job Page component can render it. It was inline in the board only (the
   landing never rendered descriptions), which is why it isn't in record.js. Kept here so
   record.js stays exactly as-is. Builds React elements via the vendored global. */
const React = window.React;

const ALLOW = { P:1, UL:1, OL:1, LI:1, B:1, STRONG:1, EM:1, I:1, BR:1, A:1, H3:1, H4:1 };

/* Some employers publish the description as one unbroken run of plain text with no
   markup at all (Dollar General: 196/196 records, zero tags). The section labels are
   still there verbatim, so we re-insert the breaks the source dropped — split only at
   a label that literally appears in the text, never reworded, nothing added or removed
   (verified: 0 characters lost across all 196). Records that ship real HTML skip this
   path entirely. Bullets are NOT reconstructed: the source gives no boundary for them,
   so a list here would be a guess. */
const BARE_SECTIONS = ["Company Overview","Job Details","Qualifications","WORKING CONDITIONS",
  "Benefits","Requirements","Responsibilities","Job Summary","Position Summary","Overview"];
const COLON_LABEL = /(^|[.!?;)”"’\s])((?:[A-Z][A-Za-z&\/]*(?:\s+(?:and\/or|and|or|of|the|to|for|with|a|in))?\s*){1,6}):\s/;

function splitColonLabels(text){
  const out = [];
  let t = text;
  for (;;) {
    const m = COLON_LABEL.exec(t);
    if (!m) { const r = t.trim(); if (r) out.push({ h: false, text: r }); break; }
    const start = m.index + m[1].length;
    const label = m[2].trim();
    if (label.split(/\s+/).length > 6 || /^(www|http)/i.test(label)) {
      const r = t.trim(); if (r) out.push({ h: false, text: r }); break;
    }
    const before = t.slice(0, start).trim();
    if (before) out.push({ h: false, text: before });
    out.push({ h: true, text: label });
    t = t.slice(start + label.length + 1);
  }
  return out;
}

function segmentPlainText(text){
  const t = String(text).replace(/\s+/g, " ").trim();
  const marks = [];
  BARE_SECTIONS.forEach((b) => {
    let i = 0;
    while ((i = t.indexOf(b, i)) >= 0) { marks.push({ at: i, len: b.length, label: b }); i += b.length; }
  });
  marks.sort((a, b) => a.at - b.at);
  const kept = marks.filter((x, i) => i === 0 || x.at >= marks[i - 1].at + marks[i - 1].len);
  const parts = [];
  let cur = 0;
  kept.forEach((h) => {
    if (h.at > cur) parts.push({ h: false, raw: t.slice(cur, h.at) });
    parts.push({ h: true, text: h.label });
    cur = h.at + h.len;
    if (t.charAt(cur) === ":") cur++;
  });
  parts.push({ h: false, raw: t.slice(cur) });

  const blocks = [];
  parts.forEach((p) => {
    if (p.h) { blocks.push(p); return; }
    splitColonLabels(p.raw).forEach((b) => {
      const clean = b.text.replace(/^[_\s:·•-]+/, "").replace(/\s+_\s*$/, "").trim();
      if (clean) blocks.push({ h: b.h, text: clean });
    });
  });
  return blocks.map((b) => React.createElement(b.h ? "h3" : "p", { key: blocks.indexOf(b) }, b.text));
}

const _descCache = {};
export function description(r){
  const key = r.internal_id;
  if (_descCache[key]) return _descCache[key];
  const src = r.description_html || "";
  if (!/<[a-z][a-z0-9]*[\s>\/]/i.test(src)) {          // no markup at all in the source
    _descCache[key] = React.createElement("div", { "data-desc-html": "true" }, segmentPlainText(src));
    return _descCache[key];
  }
  const doc = new DOMParser().parseFromString('<div id="r">' + src + '</div>', "text/html");
  const root = doc.getElementById("r");
  const walk = (node) => {
    Array.prototype.slice.call(node.children).forEach(walk);
    if (node === root) return;
    const tag = node.tagName;
    if (!ALLOW[tag]) {                                  // unwrap div/span wrappers
      const p = node.parentNode;
      while (node.firstChild) p.insertBefore(node.firstChild, node);
      p.removeChild(node);
      return;
    }
    Array.prototype.slice.call(node.attributes).forEach((a) => {
      if (!(tag === "A" && a.name === "href")) node.removeAttribute(a.name);
    });
    if (tag === "A") { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener"); }
    const empty = !node.textContent.replace(/\u00a0/g, " ").trim() && !node.querySelector("br, a");
    if ((tag === "P" || tag === "LI") && empty) node.remove();
  };
  walk(root);
  walk(root);                                           // second pass: nested wrappers
  // Workday emits one <ul> per bullet; merge runs so the list reads as a list
  Array.prototype.slice.call(root.querySelectorAll("ul, ol")).forEach((ul) => {
    const prev = ul.previousElementSibling;
    if (prev && prev.tagName === ul.tagName) {
      while (ul.firstChild) prev.appendChild(ul.firstChild);
      ul.remove();
    }
  });
  Array.prototype.slice.call(root.childNodes).forEach((n) => {   // wrap orphan text runs
    if (n.nodeType === 3 && n.textContent.replace(/\u00a0/g, " ").trim()) {
      const p = doc.createElement("p");
      p.textContent = n.textContent;
      root.replaceChild(p, n);
    }
  });
  const html = root.innerHTML;
  _descCache[key] = React.createElement("div", { "data-desc-html": "true", dangerouslySetInnerHTML: { __html: html } });
  return _descCache[key];
}
