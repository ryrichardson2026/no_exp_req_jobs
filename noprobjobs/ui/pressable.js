/* Shared press-state wrapper for the C1 depth system. Press states MUST be JS-driven:
   iOS Safari — the whole audience's browser — does not apply :active unless a touch
   handler is bound, so CSS :active alone looks right on desktop and is dead on a phone
   (reproduced live, per the plan). This binds the exact handler set the plan specifies
   and hands the pressed flag back to the caller, which computes its own pressed style
   (card offset collapse, tile shift, CTA bevel invert).

   A press state is NOT a loading state: Apply leaves for an external ATS and the press
   ends before the new tab appears, so that action still needs its own signal elsewhere.

   Class component to match the codebase (no hooks); renders `tag` (default div) with the
   .pressable utility plus styleFor(pressed). Any other prop (href, onClick, role, aria-*,
   target, rel, type, tabIndex, onKeyDown, key) passes straight through to the element. */
import { h } from "./h.js";
const React = window.React;

const OWN = { tag: 1, styleFor: 1, children: 1, className: 1, style: 1 };

export class Pressable extends React.Component {
  state = { pressed: false };
  on = () => this.setState({ pressed: true });
  off = () => { if (this.state.pressed) this.setState({ pressed: false }); };
  render(){
    const p = this.props;
    const pass = {};
    for (const k in p) if (!OWN[k]) pass[k] = p[k];
    return h(p.tag || "div", Object.assign(pass, {
      className: ["pressable", p.className].filter(Boolean).join(" "),
      style: p.styleFor(this.state.pressed),
      onTouchStart: this.on, onTouchEnd: this.off, onTouchCancel: this.off,
      onMouseDown: this.on, onMouseUp: this.off, onMouseLeave: this.off,
    }), p.children);
  }
}
