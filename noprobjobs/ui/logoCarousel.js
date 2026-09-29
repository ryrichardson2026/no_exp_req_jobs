/* Auto-scrolling employer-logo strip ("See jobs from employers like:"), shared by the About /
   Partners pages and the landing page. brands = [{ name, file }]; the file lives at /logos/.
   The strip pauses on hover and, under prefers-reduced-motion, stops and wraps instead of
   scrolling. headingCss lets a host page pass its own section-heading style so the heading
   matches the surrounding page (the landing uses a different heading style than the alert
   pages). Returns null when there are no brands. */
import { h, s } from "./h.js";

const CSS =
  "@keyframes npj-marq{from{transform:translateX(0)}to{transform:translateX(-50%)}}"
  + ".npj-marquee{overflow:hidden;position:relative;-webkit-mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent);mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent)}"
  + ".npj-marquee-track{display:flex;align-items:center;gap:34px;width:max-content;animation:npj-marq 55s linear infinite}"
  + ".npj-marquee:hover .npj-marquee-track{animation-play-state:paused}"
  + "@media(prefers-reduced-motion:reduce){.npj-marquee-track{animation:none;flex-wrap:wrap;width:auto;justify-content:center;gap:18px 30px}}";

const DEFAULT_HEAD = "margin:0 0 3px;font-family:var(--font-display);font-weight:800;font-size:19px;line-height:1.2;letter-spacing:0.01em;color:var(--ink);padding-bottom:10px;border-bottom:2px solid var(--mark)";

export function logoCarousel(brands, headingCss){
  if (!brands || !brands.length) return null;
  const logo = (b, i) => h("div", { key: i, style: s("flex:none;display:flex;align-items:center;justify-content:center;height:46px") },
    h("img", { src: "/logos/" + b.file, alt: b.name, height: 36, loading: "lazy",
      style: s("height:36px;max-width:132px;width:auto;object-fit:contain;display:block") }));
  const loop = brands.concat(brands).map(logo);   // two copies -> seamless -50% loop
  return h("section", { style: s("display:grid;gap:16px") },
    h("h2", { style: s(headingCss || DEFAULT_HEAD) }, "See jobs from employers like:"),
    h("style", { dangerouslySetInnerHTML: { __html: CSS } }),
    h("div", { className: "npj-marquee" }, h("div", { className: "npj-marquee-track" }, loop)));
}
