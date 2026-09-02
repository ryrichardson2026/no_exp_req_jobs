#!/usr/bin/env python3
"""
analyze/card.py - render one job card from the normalized contract, as SVG.

CONTRACT ONLY. No adapter import, no `if tenant ==`, no source branch. Four
employers with four fill profiles go through ONE code path. The only thing that
changes between cards is which fields are populated - and the renderer's rule is:
render what exists, omit what doesn't, never fabricate a placeholder. A field
that is null produces no element, not an empty row. salary_is_stated False means
no pay element at all. A modality with no entries means no header.

Mobile-first: a phone-width card, read standing outside, not at a desk.

Run:  python -m analyze.card            # writes out/cards.svg (the four exemplars)
"""

import datetime
import glob
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APPLICABLE = os.path.join(ROOT, "out", "applicable.jsonl")
TODAY = datetime.date(2026, 9, 1)          # currentDate; card.py takes no clock

# --- layout tokens (px) ------------------------------------------------------
W, PAD = 360, 22
INNER = W - 2 * PAD
GAP = 26
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "Helvetica,Arial,sans-serif")

INK, SUB, FAINT = "#0f172a", "#475569", "#94a3b8"
LINE = "#e2e8f0"
PAY_BG, PAY_INK = "#dcfce7", "#166534"
EXP_BG, EXP_INK = "#e0f2fe", "#075985"
NEU_BG, NEU_INK = "#f1f5f9", "#475569"
PATH_BG, PATH_INK, PATH_TAG = "#ecfdf5", "#065f46", "#10b981"
NEED_MK = "#f59e0b"        # to-apply requirement marker
PREF_MK = "#94a3b8"        # preferred marker
BRAND = "#1d4ed8"


def esc(s):
    return html.escape(str(s), quote=True)


# approx text width so we can wrap without a layout engine
_WIDE = set("mwMW@")
_NARROW = set("iljtfrI.,:;'!| ")


def _char_w(c, fs):
    if c in _WIDE:
        return fs * 0.82
    if c in _NARROW:
        return fs * 0.30
    if c.isupper():
        return fs * 0.66
    return fs * 0.52


def text_w(s, fs):
    return sum(_char_w(c, fs) for c in s)


def wrap(s, fs, width, max_lines=None):
    words, lines, cur = s.split(), [], ""
    for wd in words:
        trial = wd if not cur else cur + " " + wd
        if text_w(trial, fs) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and text_w(lines[-1] + "…", fs) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + "…"
    return lines


def rel_date(posted):
    if not posted:
        return None
    try:
        d = datetime.date.fromisoformat(str(posted)[:10])
    except ValueError:
        return None
    n = (TODAY - d).days
    if n < 0:
        return None
    if n == 0:
        return "Posted today"
    if n == 1:
        return "Posted yesterday"
    if n <= 30:
        return f"Posted {n} days ago"
    return "Posted " + d.strftime("%b %-d") if os.name != "nt" \
        else "Posted " + d.strftime("%b %#d")


def money(r):
    lo, hi = r.get("salary_min"), r.get("salary_max")
    per = {"HOURLY": "/hr", "ANNUAL": "/yr", "WEEKLY": "/wk",
           "MONTHLY": "/mo", "DAILY": "/day"}.get(r.get("pay_period"), "")
    def f(x):
        return f"${x:,.2f}" if x % 1 else f"${x:,.0f}"
    if lo and hi and lo != hi:
        return f"{f(lo)}–{f(hi)}{per}"
    return f"{f(lo or hi)}{per}"


# ---------------------------------------------------------------------------
# ONE renderer. Builds a list of (svg_fragment, height) blocks, top to bottom,
# appending a block only when the field behind it is present.
# ---------------------------------------------------------------------------

def render_card(r, x0, y0):
    S, y = [], y0 + PAD
    L = x0 + PAD

    def line(txt, fs, fill, weight="400", dy_before=0, ls="0",
             lh=1.32, max_lines=None, width=INNER):
        nonlocal y
        y += dy_before
        for ln in wrap(txt, fs, width, max_lines):
            y += fs
            S.append(f'<text x="{L}" y="{y:.0f}" font-size="{fs}" '
                     f'fill="{fill}" font-weight="{weight}" '
                     f'letter-spacing="{ls}">{esc(ln)}</text>')
            y += fs * (lh - 1)

    def chips(items):
        nonlocal y
        if not items:
            return
        y += 12
        cx, cy = L, y
        fs, ph, pv = 12, 9, 6
        rowh = fs + 2 * pv
        for label, bg, ink in items:
            w = text_w(label, fs) + 2 * ph
            if cx + w > L + INNER + 1 and cx > L:
                cx = L
                cy += rowh + 6
            S.append(f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{w:.0f}" '
                     f'height="{rowh}" rx="{rowh/2:.0f}" fill="{bg}"/>')
            S.append(f'<text x="{cx+w/2:.0f}" y="{cy+rowh/2+fs*0.35:.0f}" '
                     f'font-size="{fs}" fill="{ink}" text-anchor="middle" '
                     f'font-weight="600">{esc(label)}</text>')
            cx += w + 6
        y = cy + rowh

    def rule():
        nonlocal y
        y += 16
        S.append(f'<line x1="{L}" y1="{y:.0f}" x2="{L+INNER}" y2="{y:.0f}" '
                 f'stroke="{LINE}"/>')

    def header(txt):
        line(txt.upper(), 10.5, FAINT, weight="700", dy_before=16, ls="0.8")

    def clause(txt, mk):
        nonlocal y
        y += 8
        top = y
        for i, ln in enumerate(wrap(txt, 12.5, INNER - 14)):
            y += 12.5
            if i == 0:
                S.append(f'<circle cx="{L+3:.0f}" cy="{y-4:.0f}" r="2.4" '
                         f'fill="{mk}"/>')
            S.append(f'<text x="{L+14}" y="{y:.0f}" font-size="12.5" '
                     f'fill="{SUB}">{esc(ln)}</text>')
            y += 12.5 * 0.3

    def path_block(cred):
        nonlocal y
        y += 10
        txt = cred["text"]
        tf = cred.get("timeframe_months")
        when = ""
        # Only synthesize a timeframe line when the clause text doesn't already
        # carry one - otherwise we'd echo "within 12 months" twice.
        if tf and not any(w in txt.lower() for w in ("month", "week", "day", "year")):
            m = int(tf)
            when = f"within {m} month{'s' if m != 1 else ''} of hire"
        lines = wrap(txt, 12.5, INNER - 24)
        panelh = 16 + 15 + len(lines) * 16 + (16 if when else 0)
        top = y
        S.append(f'<rect x="{L}" y="{y:.0f}" width="{INNER}" '
                 f'height="{panelh:.0f}" rx="10" fill="{PATH_BG}"/>')
        S.append(f'<rect x="{L}" y="{y:.0f}" width="4" height="{panelh:.0f}" '
                 f'rx="2" fill="{PATH_TAG}"/>')
        yy = y + 20
        S.append(f'<text x="{L+14}" y="{yy:.0f}" font-size="10.5" '
                 f'fill="{PATH_TAG}" font-weight="700" '
                 f'letter-spacing="0.6">EARN AFTER YOU START → NOT A '
                 f'BARRIER</text>')
        for ln in lines:
            yy += 16
            S.append(f'<text x="{L+14}" y="{yy:.0f}" font-size="12.5" '
                     f'fill="{PATH_INK}" font-weight="600">{esc(ln)}</text>')
        if when:
            yy += 16
            S.append(f'<text x="{L+14}" y="{yy:.0f}" font-size="11.5" '
                     f'fill="{PATH_INK}">{esc(when)}</text>')
        y = top + panelh

    # ---- HEADER (always) ----
    line(r["title"], 17, INK, weight="700", lh=1.24, max_lines=2)
    line(r["company_name"], 13, SUB, weight="600", dy_before=4, max_lines=1)
    loc = ", ".join(p for p in (r.get("city"), r.get("state")) if p)
    posted = rel_date(r.get("posted_at"))
    sub = " · ".join(p for p in (loc, posted) if p)
    if sub:
        line(sub, 12, FAINT, dy_before=2)

    # ---- META CHIPS (each conditional) ----
    ch = []
    exp = r.get("experience_condition")
    exp_label = {"NONE_NEEDED": "No experience needed",
                 "WAIVED": "Experience waived",
                 "PREFERRED": "Experience preferred, not required"}.get(exp)
    if exp_label:
        ch.append((exp_label, EXP_BG, EXP_INK))
    if r.get("salary_is_stated"):
        ch.append((money(r), PAY_BG, PAY_INK))
    if r.get("employment_type"):
        ch.append((r["employment_type"], NEU_BG, NEU_INK))
    if r.get("shift_raw"):
        ch.append((f"{r['shift_raw']} shift", NEU_BG, NEU_INK))
    if r.get("fte"):
        ch.append((f"{r['fte']:g} FTE", NEU_BG, NEU_INK))
    chips(ch)

    # ---- DESCRIPTION lead (always) ----
    dt = " ".join((r.get("description_text") or "").split())
    if dt:
        rule()
        line(dt, 12.5, SUB, dy_before=14, lh=1.4, max_lines=3)

    # The raw qualifications block is NOT rendered. The extractor already parses
    # it into requirement clauses (that is the input Kroger's section detection
    # depends on), and those render below under their modality. Rendering the raw
    # block too would show the same content twice with one copy unlabelled - and
    # its preferred text would duplicate the "Nice to have" line. Option (a).

    # ---- REQUIREMENTS by modality, credentials merged in, deduped ----
    creds = r.get("credentials") or []
    cred_txt = {c["text"] for c in creds}
    ev = r.get("evidence_clauses") or []

    def modal(modality, title, marker):
        rows = [e["clause"] for e in ev
                if e.get("modality") == modality and e["clause"] not in cred_txt]
        rows += [c["text"] for c in creds if c["modality"] == modality]
        seen, uniq = set(), []
        for t in rows:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        if uniq:
            header(title)
            for t in uniq:
                clause(" ".join(t.split()), marker)

    # Two sections, modality is the organising principle. A credential is a
    # requirement: it renders under whichever modality it carries, not in a
    # separate "Credentials" block. BLS required to apply sits under "To apply".
    modal("TO_APPLY", "To apply, you need", NEED_MK)
    modal("PREFERRED", "Nice to have", PREF_MK)

    # ---- AFTER-HIRE credentials render as a PATH, never a barrier ----
    # Its own visual element, below the two requirement sections. No header - the
    # green panel's own tag labels it, and it is not a requirement to apply.
    for c in creds:
        if c["modality"] == "AFTER_HIRE":
            path_block(c)

    # ---- APPLY (always) ----
    if r.get("apply_url"):
        y += 22
        bh = 44
        S.append(f'<rect x="{L}" y="{y:.0f}" width="{INNER}" height="{bh}" '
                 f'rx="{bh/2:.0f}" fill="{BRAND}"/>')
        S.append(f'<text x="{L+INNER/2:.0f}" y="{y+bh/2+5:.0f}" '
                 f'font-size="14.5" fill="#ffffff" text-anchor="middle" '
                 f'font-weight="700">Apply on employer site →</text>')
        y += bh

    y += PAD
    card_h = y - y0
    frame = (f'<rect x="{x0}" y="{y0}" width="{W}" height="{card_h:.0f}" '
             f'rx="20" fill="#ffffff" stroke="{LINE}" stroke-width="1"/>')
    return frame + "".join(S), card_h


def load_exemplars():
    recs = [json.loads(l) for l in open(APPLICABLE, encoding="utf-8")]

    def first(pred):
        return next(r for r in recs if pred(r))

    return [
        # no pay (tenant-wide), a credential required TO APPLY (renders under
        # "To apply") AND after-hire credentials (render as paths) - shows the
        # consolidation: modality places the credential, not its name.
        first(lambda r: "MultiCare" in (r["company_name"] or "")
              and not r.get("salary_is_stated")
              and any(c["modality"] == "TO_APPLY" for c in (r.get("credentials") or []))
              and any(c["modality"] == "AFTER_HIRE" for c in (r.get("credentials") or []))
              and r.get("employment_type")),
        first(lambda r: r["company_name"] == "Target" and r.get("salary_is_stated")),
        first(lambda r: r["company_name"] in ("Fred Meyer", "Quality Food Centers")
              and r.get("qualifications")),
        first(lambda r: r["company_name"].startswith("Providence")
              and r.get("shift_raw") and r.get("fte") and r.get("credentials")),
    ]


def main():
    cards = load_exemplars()
    margin = 28
    bodies, heights = [], []
    x = margin
    for r in cards:
        body, h = render_card(r, x, margin + 40)
        bodies.append(body)
        heights.append(h)
        x += W + GAP
    sheet_w = margin * 2 + len(cards) * W + (len(cards) - 1) * GAP
    sheet_h = margin + 40 + max(heights) + margin
    labels = []
    lx = margin
    for r in cards:
        labels.append(
            f'<text x="{lx+W/2:.0f}" y="{margin+20:.0f}" font-size="12" '
            f'fill="#64748b" text-anchor="middle" font-weight="600" '
            f'letter-spacing="0.4">{esc(r["company_name"].split(" /")[0])}'
            f'</text>')
        lx += W + GAP
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{sheet_w:.0f}" '
        f'height="{sheet_h:.0f}" viewBox="0 0 {sheet_w:.0f} {sheet_h:.0f}" '
        f'font-family="{FONT}">'
        f'<rect width="{sheet_w:.0f}" height="{sheet_h:.0f}" fill="#f8fafc"/>'
        + "".join(labels) + "".join(bodies) + "</svg>")
    out = os.path.join(ROOT, "out", "cards.svg")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"wrote {out}  ({sheet_w:.0f}x{sheet_h:.0f})")
    for r, h in zip(cards, heights):
        flags = []
        if not r.get("salary_is_stated"):
            flags.append("no-pay")
        if not r.get("employment_type"):
            flags.append("no-emp-type")
        if r.get("shift_raw"):
            flags.append("shift")
        if r.get("fte"):
            flags.append("fte")
        if r.get("qualifications"):
            flags.append("quals-block")
        if any(c["modality"] == "AFTER_HIRE" for c in (r.get("credentials") or [])):
            flags.append("after-hire-cred")
        print(f"  {r['company_name'].split(' /')[0]:<14} h={h:.0f}  "
              f"{r['title'][:42]:<42} [{', '.join(flags)}]")


if __name__ == "__main__":
    main()
