"""
normalize/experience.py - requirement extraction.

ONE IMPLEMENTATION PER CONCEPT. Requirements extraction lives in exactly this
file. Experience and credential are requirement TYPES, not separate extractors -
a food handler card is another entry in the same list.

WHAT IS SHARED AND WHAT IS FORKED.

  SHARED (never forked): the record shape (normalize/model.py), the five
  conditions, the four gates, and this typing/derivation ENGINE - classify_line,
  derive_condition, the cue lists, the section-span logic. Every layer above reads
  one contract.

  FORKED PER TENANT: the OPENER VOCABULARY and its MATCHING MODE. Each tenant's
  config (config/tenants.json -> extraction.openers) carries its own list of
  opener strings, each tagged with a role (REQUIRED/PREFERRED) and a match mode.
  Adapters do not share code with each other, and extraction vocabulary is now
  covered by that rule: a Target opener string can never change how MultiCare
  parses. Duplication of a generic heading across tenants is correct, not waste.

MATCH MODES (a tenant declares which each of its openers uses):
  colon   heading followed by a colon, matched ANYWHERE in a line. The colon is
          load-bearing - it separates a heading from prose like "...meet required
          qualifications and conditions for payment" - and matching anywhere is
          what catches a mid-line heading (MultiCare "Additional Requirements:",
          Kroger "...& Education Requirements:", Target "...from the get-go:").
  bare    a bare word/phrase on its own line, colon-less (Kroger "Minimum").
  prefix  a heading that leads its line colon-less, the first item following on
          the same line (MultiCare "Requirements High school diploma...").
  line    line-anchored, alnum-compared so a stray intra-word space is healed
          (Target's blocks carry "ever y thing" / "m ay"); whole-line or leading.

WHY SECTIONS, NOT PHRASES. A required section is ENUMERATED, then the condition
is DERIVED. Experience absent from a POPULATED required list is a positive finding
and stronger than a marketing line. Absence counts only where a required section
was found AND had content; otherwise NOT_STATED - a parser miss must never read as
"no experience required". "Upon hire" / "within 30 days" attach AFTER hiring and
are not barriers to applying.
"""

import argparse
import html as _html
import json
import os
import re
import sys

NONE_NEEDED = "NONE_NEEDED"
WAIVED = "WAIVED"
REQUIRED = "REQUIRED"
PREFERRED = "PREFERRED"
NOT_STATED = "NOT_STATED"
PRECEDENCE = (REQUIRED, PREFERRED, WAIVED, NONE_NEEDED, NOT_STATED)

TO_APPLY = "TO_APPLY"
PREFERRED_M = "PREFERRED"
AFTER_HIRE = "AFTER_HIRE"

EXPERIENCE, EDUCATION, CREDENTIAL = "experience", "education", "credential"
TRAINING, BACKGROUND, PHYSICAL = "training", "background", "physical"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config", "tenants.json")


# ---------------------------------------------------------------------------
# section terminators - SHARED. These fence off benefits/About/EEO/award/marketing
# text once a section is over; they are not opener vocabulary and are not forked.
# ---------------------------------------------------------------------------

END_HEADINGS = (
    "why join", "about providence", "about the team", "about us",
    "our best-in-class", "equal opportunity", "eeo", "applicants in the",
    "posted are the minimum", "we offer", "total rewards", "salary range",
    "pay range", "benefits", "learn more at", "for any concerns",
    "pay and benefit expectations",
)

END_RX = re.compile(
    "|".join(re.escape(h) for h in sorted(END_HEADINGS, key=len, reverse=True)),
    re.IGNORECASE)
# "about" fences "About <any facility>" (MultiCare award blurbs) line-anchored so it
# cannot misfire mid-line in "obtain within about 2 weeks".
MC_MARKETING_END_RX = re.compile(r"(?im)^[ \t]*about\b")


# ---------------------------------------------------------------------------
# opener matchers - built PER TENANT from the injected vocabulary
# ---------------------------------------------------------------------------

def _alnum(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _role_kind(role):
    return TO_APPLY if str(role).upper() == "REQUIRED" else PREFERRED_M


def compile_openers(spec):
    """Turn a tenant's extraction.openers list into compiled matchers. Each opener
    is {text, role, match}. Returns a dict consumed by sectionize."""
    spec = spec or []
    colon = [(o["text"], o["role"]) for o in spec if o.get("match") == "colon"]
    bare = [(o["text"], o["role"]) for o in spec if o.get("match") == "bare"]
    prefix = [(o["text"], o["role"]) for o in spec if o.get("match") == "prefix"]
    line = [(o["text"], o["role"]) for o in spec if o.get("match") == "line"]

    def alt(items):
        return "|".join(re.escape(t) for t, _ in
                        sorted(items, key=lambda x: len(x[0]), reverse=True))

    m = {"colon_rx": None, "colon_role": {}, "bare_rx": None, "bare_role": {},
         "prefix_rx": None, "prefix_role": {}, "line": []}
    if colon:
        # (heading)\w{0,3}\s*:  - the \w{0,3} admits the plural "...Qualifications:"
        m["colon_rx"] = re.compile(r"(" + alt(colon) + r")\w{0,3}\s*:", re.IGNORECASE)
        m["colon_role"] = {t.lower(): r for t, r in colon}
    if bare:
        m["bare_rx"] = re.compile(r"(?im)^[ \t]*(" + alt(bare) + r")[ \t]*$")
        m["bare_role"] = {t.lower(): r for t, r in bare}
    if prefix:
        m["prefix_rx"] = re.compile(r"(?im)^[ \t]*(" + alt(prefix) + r")\b(?![ \t]*:)")
        m["prefix_role"] = {t.lower(): r for t, r in prefix}
    if line:
        m["line"] = sorted(((_alnum(t), r, t) for t, r in line),
                           key=lambda x: len(x[0]), reverse=True)
    return m


def _consume_index(orig, n_alnum):
    c = 0
    for i, ch in enumerate(orig):
        if ch.isalnum():
            c += 1
            if c == n_alnum:
                return i + 1
    return None


def _line_opener(ak, orig, specs):
    """(role, content_start, heading_start) for a line-anchored (alnum-healed)
    opener, else None. Whole-line or leading; a <=3 alnum plural tail is allowed."""
    for key, role, _raw in specs:
        if not ak.startswith(key):
            continue
        for tail in range(0, 4):
            need = len(key) + tail
            if need > len(ak):
                break
            idx = _consume_index(orig, need)
            if idx is None:
                continue
            nextch = orig[idx] if idx < len(orig) else ""
            if nextch == "" or not nextch.isalnum():
                j = idx
                while j < len(orig) and orig[j] in " \t":
                    j += 1
                if j < len(orig) and orig[j] == ":":
                    j += 1
                lead = len(orig) - len(orig.lstrip(" \t•-*–"))
                return role, j, lead
    return None


BLOCK_RX = re.compile(r"(?is)<\s*(?:br|/?p|/?li|/?div|/?ul|/?ol|/?tr|/?h[1-6])\s*/?>")
TAG_RX = re.compile(r"(?s)<[^>]+>")
_CLAUSE_SPLIT = re.compile(r"[.;!?]\s+|\n+")

# Unicode punctuation folded to ASCII BEFORE any matching. Smart quotes, en/em
# dashes and non-breaking spaces run all through employer prose; recognising them
# is a property of the TEXT, not of each pattern. Fold once here rather than
# teaching every regex a second variant - the one-implementation-per-concept rule
# applied to punctuation. A credential quick-list that knows only the ASCII
# apostrophe would otherwise silently miss "driver’s license", and a
# "what you'll need" opener would miss a "What You’ll Need:" heading.
_FOLD_TABLE = {
    0x2019: "'", 0x2018: "'",
    0x201C: '"', 0x201D: '"',
    0x2013: "-", 0x2014: "-",
    0x00A0: " ",
}


def fold_punct(s):
    return s.translate(_FOLD_TABLE) if s else s


def html_to_text(html):
    """Block tags -> newline (that is where the item boundaries are), remaining
    inline tags -> space, entities unescaped. One requirement per line."""
    s = BLOCK_RX.sub("\n", html or "")
    s = TAG_RX.sub(" ", s)
    s = _html.unescape(s)
    lines = []
    for raw in s.split("\n"):
        ln = " ".join(raw.split()).strip(" \t•-*–")
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def _clauses(body):
    for part in _CLAUSE_SPLIT.split(body):
        s = part.strip(" \t•-*–")
        if s:
            yield s


def sectionize(html, text_fallback="", qualifications_html="", openers=None):
    """{TO_APPLY: [...], PREFERRED: [...]} plus whether a required section was
    actually found. Markers come from the tenant's compiled openers (colon / bare /
    prefix / line) plus the SHARED END terminators; everything outside a
    qualifications section is discarded, and that discard is the entire point."""
    openers = openers or {}
    out = {TO_APPLY: [], PREFERRED_M: []}
    text = html_to_text(html) if (html or "").strip() else (text_fallback or "")
    if (qualifications_html or "").strip():
        qtext = html_to_text(qualifications_html)
        text = f"{text}\n{qtext}" if text else qtext
    text = fold_punct(text)

    markers = []
    if openers.get("colon_rx"):
        for m in openers["colon_rx"].finditer(text):
            markers.append((m.start(), m.end(),
                            _role_kind(openers["colon_role"][m.group(1).lower()])))
    if openers.get("bare_rx"):
        for m in openers["bare_rx"].finditer(text):
            markers.append((m.start(), m.end(),
                            _role_kind(openers["bare_role"][m.group(1).lower()])))
    if openers.get("prefix_rx"):
        for m in openers["prefix_rx"].finditer(text):
            markers.append((m.start(), m.end(),
                            _role_kind(openers["prefix_role"][m.group(1).lower()])))
    if openers.get("line"):
        off = 0
        for ln in text.split("\n"):
            ak = _alnum(ln)
            if ak:
                hit = _line_opener(ak, ln, openers["line"])
                if hit:
                    role, cstart, lead = hit
                    markers.append((off + lead, off + cstart, _role_kind(role)))
            off += len(ln) + 1
    for m in END_RX.finditer(text):
        markers.append((m.start(), m.end(), None))       # None = terminator only
    for m in MC_MARKETING_END_RX.finditer(text):
        markers.append((m.start(), m.end(), None))       # line-anchored "About ..."
    if not markers:
        return out, False
    markers.sort(key=lambda x: x[0])

    found_required = False
    for i, (start, end, kind) in enumerate(markers):
        if kind is None:
            continue                                     # END marker: discard span
        span_end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        if kind == TO_APPLY:
            found_required = True
        out[kind].extend(_clauses(text[end:span_end]))
    return out, found_required


# ---------------------------------------------------------------------------
# requirement typing - SHARED engine (not forked)
# ---------------------------------------------------------------------------

# Attaches on or after hire. Not a barrier to applying, and treating it as one
# deletes the most winnable inventory on the board.
AFTER_HIRE_CUES = (
    "upon hire", "at hire", "on hire", "within 30 days", "within 60 days",
    "within 90 days", "within six months", "within 6 months", "within one year",
    "within 1 year", "prior to start", "before start date", "post-hire",
    "after hire", "will be completed", "will be obtained", "must obtain within",
    "required within", "obtain within",
    # Kroger deli/bakery: "Ability to obtain current food handlers permit once
    # employed" - a credential earned AFTER hire, not a barrier to applying.
    "once employed",
    # MultiCare frontline: "Food Handlers Card within seven (7) days of hire" -
    # match the TIMING phrase, NOT bare "of hire" (that matched Providence's
    # "department of hire", a LOCATION, and wrongly cleared a 1-year bar on ~36).
    "days of hire", "date of hire",
)

# A requirement line that qualifies ITSELF as wanted-not-required, whatever section
# it sits in. "Serve-Safe certification preferred" under a Requirements heading is
# preferred, not a gate. After-hire wins if both are present.
PREFERRED_CUES = ("preferred", "desired", " a plus", "nice to have")

EXPERIENCE_CUES = ("experience", "years in", "yrs", "background in",
                   "work history", "previously worked", "journeyman",
                   "journey level", "journey-level")
EDUCATION_CUES = ("degree", "diploma", "ged", "high school", "coursework",
                  "graduation", "graduate of", "accredited", "bachelor",
                  "associate", "master", "doctor")
CREDENTIAL_CUES = ("license", "licence", "certification", "certificate",
                   "certified", "card", "credential", "registration",
                   "bls", "cpr", "acls", "pals", "food handler", "guard card",
                   "osha", "twic", "cdl")
TRAINING_CUES = ("on-the-job", "on the job", "will train", "we train",
                 "training will be", "training provided", "self-study",
                 "training program", "willing to learn", "willingness to learn")
BACKGROUND_CUES = ("background check", "criminal history", "drug screen",
                   "drug test", "motor vehicle report", "mvr", "fingerprint")
PHYSICAL_CUES = ("lift", "lbs", "pounds", "stand for", "bend")

# A completed trade apprenticeship is a multi-year runway even where no year count
# appears - it is what separates the Painter (4y Journeyman) from the Engineer
# (training will be on-the-job).
TRADE_TICKET = ("journeyman", "journey level", "journey-level", "red seal",
                "master electrician", "master plumber", "ticketed")

WORD_NUMBERS = {"zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3,
                "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
_W = "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))

DURATION = re.compile(
    r"\b(?:(\d+(?:\.\d+)?)|(" + _W + r"))\s*(?:\(\s*\d+\s*\)\s*)?"
    r"(?:\+|plus)?\s*(?:to|-|–|or)?\s*"
    r"(?:\d+(?:\.\d+)?|" + _W + r")?\s*(?:\(\s*\d+\s*\)\s*)?"
    r"(years?|yrs?|months?|mos?)\b", re.IGNORECASE)

RECURRENCE = re.compile(r"\bevery\s+\d+\s*(?:years?|months?)", re.IGNORECASE)

WAIVER_RX = (
    r"\bin lieu of experience\b",
    r"\bexperience (?:may|can|will) be (?:substituted|accepted)\b",
    r"\bno experience (?:is )?(?:required|necessary|needed)\b",
    r"\bexperience (?:is )?not required\b",
    # "No prior experience required" - the exact and only waiver phrasing on Allied
    # (36 of 146). The bare "no experience ..." pattern above misses the interposed
    # "prior", so a genuine no-experience posting read as REQUIRED. Scoped to
    # "prior" because that is the sole form measured on this board; "previous" and
    # other synonyms are deliberately NOT added - nobody uses them, and a WAIVER
    # phrase that over-matches clears real bars (cf. the "of hire" precedent).
    r"\bno prior experience (?:is )?(?:required|necessary|needed)\b",
)


def parse_duration_months(s):
    best = None
    for m in DURATION.finditer(s):
        num, unit = (m.group(1) or m.group(2)), m.group(3).lower()
        try:
            v = float(num) if m.group(1) else float(WORD_NUMBERS[num.lower()])
        except (ValueError, KeyError):
            continue
        mo = v * 12 if unit.startswith(("year", "yr")) else v
        best = mo if best is None else min(best, mo)
    return best


def classify_line(line, section_modality):
    low = line.lower()

    modality = section_modality
    if any(c in low for c in AFTER_HIRE_CUES):
        modality = AFTER_HIRE
    elif any(c in low for c in PREFERRED_CUES):
        modality = PREFERRED_M

    types = []
    for cues, name in ((BACKGROUND_CUES, BACKGROUND), (TRAINING_CUES, TRAINING),
                       (CREDENTIAL_CUES, CREDENTIAL), (EDUCATION_CUES, EDUCATION),
                       (EXPERIENCE_CUES, EXPERIENCE), (PHYSICAL_CUES, PHYSICAL)):
        if any(c in low for c in cues):
            types.append(name)
    if not types:
        return None

    months = parse_duration_months(line)
    if months is not None and (RECURRENCE.search(low) or
                               (BACKGROUND in types and EXPERIENCE not in types)):
        months = None

    return {"clause": line[:300], "types": types, "modality": modality,
            "months": months,
            "trade_ticket": any(t in low for t in TRADE_TICKET)}


def derive_condition(reqs, found_required):
    """Absence counts only where a section was actually read. A populated required
    section with nothing blocking application - including one whose every item is
    AFTER_HIRE - is NONE_NEEDED, not NOT_STATED. After-hire items ARE content."""
    to_apply = [r for r in reqs if r["modality"] == TO_APPLY]
    apply_exp = [r for r in to_apply if EXPERIENCE in r["types"]]
    pref_exp = [r for r in reqs
                if r["modality"] == PREFERRED_M and EXPERIENCE in r["types"]]

    waiver = [r for r in reqs
              if any(re.search(p, r["clause"].lower()) for p in WAIVER_RX)]
    if waiver:
        return WAIVED, waiver
    if apply_exp:
        return REQUIRED, apply_exp
    if not found_required or not reqs:
        return NOT_STATED, []
    if pref_exp:
        return PREFERRED, pref_exp
    return NONE_NEEDED, to_apply or reqs


def extract(html, text_fallback="", qualifications_html="", openers=None):
    sections, found_required = sectionize(html, text_fallback, qualifications_html, openers)
    reqs = []
    for modality, lines in ((TO_APPLY, sections[TO_APPLY]),
                            (PREFERRED_M, sections[PREFERRED_M])):
        for line in lines:
            r = classify_line(line, modality)
            if r:
                reqs.append(r)

    condition, evidence = derive_condition(reqs, found_required)
    to_apply = [r for r in reqs if r["modality"] == TO_APPLY]
    months = [r["months"] for r in to_apply
              if EXPERIENCE in r["types"] and r["months"]]

    return {
        "experience_condition": condition,
        "evidence_clauses": [{"label": condition, "clause": r["clause"],
                              "types": r["types"], "modality": r["modality"],
                              "months": r["months"]} for r in evidence][:10],
        "requirements": reqs,
        "section_found": found_required,
        "min_months": min(months) if months else None,
        "trade_ticket": any(r["trade_ticket"] for r in to_apply),
        "credentials_to_apply": [r["clause"] for r in to_apply
                                 if CREDENTIAL in r["types"]],
        "credentials_after_hire": [r["clause"] for r in reqs
                                   if r["modality"] == AFTER_HIRE
                                   and CREDENTIAL in r["types"]],
        # Contract shape: every named credential with its modality and timeframe.
        # Superset of the two lists above (which stay, being what the gate reads).
        # modality is TO_APPLY / PREFERRED / AFTER_HIRE; timeframe_months is the
        # parsed duration where the clause states one, else None.
        "credentials": [{"text": r["clause"], "modality": r["modality"],
                         "timeframe_months": r["months"]}
                        for r in reqs if CREDENTIAL in r["types"]],
    }


def load_openers(tenant):
    """Read a tenant's forked opener vocabulary from config. Searches every platform
    section for the tenant key. Returns the compiled matchers."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    for platform, tenants in cfg.items():
        if isinstance(tenants, dict) and tenant in tenants \
                and isinstance(tenants[tenant], dict):
            ext = tenants[tenant].get("extraction") or {}
            return compile_openers(ext.get("openers") or [])
    sys.exit(f"tenant '{tenant}' not found in {CONFIG_PATH}")


def main():
    ap = argparse.ArgumentParser(description="Requirement extraction")
    ap.add_argument("--input", required=True)
    ap.add_argument("--tenant", required=True,
                    help="tenant key in config/tenants.json - selects the forked "
                         "opener vocabulary")
    ap.add_argument("--output")
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--audit", action="store_true")
    a = ap.parse_args()

    openers = load_openers(a.tenant)

    with open(a.input, "r", encoding="utf-8") as fh:
        recs = [json.loads(l) for l in fh if l.strip()]
    if not recs:
        sys.exit("no records")

    for r in recs:
        out = extract(r.get("description_html") or "", r.get("description_text") or "",
                      r.get("qualifications_html") or "", openers)
        r["experience_condition"] = out["experience_condition"]
        r["evidence_clauses"] = out["evidence_clauses"]
        r["_x"] = out

    n = len(recs)
    print("=" * 78)
    print(f"REQUIREMENT EXTRACTION - {a.tenant} - {n} records")
    print("Opener vocabulary is forked per tenant (config.extraction.openers).")
    print("Reads ONLY qualifications sections; benefits/About/award text is out")
    print("of scope by construction.")
    print("=" * 78)

    sec = sum(1 for r in recs if r["_x"]["section_found"])
    print("\n### SECTION DETECTION - the load-bearing number\n")
    print(f"  {sec}/{n} ({sec/n*100:.1f}%) had a required-qualifications section "
          f"found and parsed.")
    print("  The rest can only be NOT_STATED. If this number is low, everything")
    print("  below is under-counted and section detection is the thing to fix.")

    print("\n### DISTRIBUTION\n")
    dist = {}
    for r in recs:
        dist[r["experience_condition"]] = dist.get(r["experience_condition"], 0) + 1
    for k in PRECEDENCE:
        c = dist.get(k, 0)
        print(f"  {c:>5}  {c/n*100:>5.1f}%  {k:<12} {'#' * int(c/n*30)}")

    tk = sum(1 for r in recs if r["_x"]["trade_ticket"])
    print(f"\n  {tk} carry a trade ticket (journeyman / master / red seal).")

    print("\n### CREDENTIALS\n")
    ca = sum(1 for r in recs if r["_x"]["credentials_to_apply"])
    ch = sum(1 for r in recs if r["_x"]["credentials_after_hire"])
    print(f"  {ca:>5} require a credential TO APPLY")
    print(f"  {ch:>5} require one AFTER HIRE - not a barrier. This is winnable.")

    print("\n### OPEN INVENTORY BY FUNCTION\n")
    rows = {}
    for r in recs:
        k = r.get("source_function") or "(none)"
        rows.setdefault(k, {})
        c = r["experience_condition"]
        rows[k][c] = rows[k].get(c, 0) + 1
    w = max((len(k) for k in rows), default=10)
    print(f"  {'function':<{w}}" + "".join(f"{s[:9]:>11}" for s in PRECEDENCE) +
          f"{'total':>8}{'  open%':>8}")
    for k, d in sorted(rows.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(d.values())
        op = d.get(NONE_NEEDED, 0) + d.get(WAIVED, 0)
        print(f"  {k:<{w}}" + "".join(f"{d.get(s,0):>11}" for s in PRECEDENCE) +
              f"{tot:>8}{op/tot*100:>7.0f}%")

    if a.audit:
        print("\n\n" + "=" * 78)
        print("AUDIT - requirement lines by modality and type")
        print("=" * 78)
        groups = {}
        for r in recs:
            for req in r["_x"]["requirements"]:
                for t in req["types"]:
                    groups.setdefault((req["modality"], t), []).append(
                        (r.get("title"), req["clause"]))
        for key in sorted(groups, key=lambda k: -len(groups[k])):
            hits = groups[key]
            print(f"\n  {key[0]} / {key[1]}   {len(hits)} lines")
            for title, clause in hits[:8]:
                print(f"     - {clause[:150]}")
                print(f"       ^ {title}")
            if len(hits) > 8:
                print(f"     ... {len(hits) - 8} more")
    else:
        print("\n" + "=" * 78)
        print("SAMPLES - read these")
        print("=" * 78)
        for label in PRECEDENCE:
            sub = [r for r in recs if r["experience_condition"] == label]
            print(f"\n\n--- {label}  ({len(sub)}) ---")
            for r in sub[:a.samples]:
                x = r["_x"]
                print(f"\n  [{r.get('source_function')}] {r.get('title')}")
                print(f"  section_found={x['section_found']}  "
                      f"months={x['min_months']}  ticket={x['trade_ticket']}")
                for req in x["requirements"][:5]:
                    print(f"    {req['modality']:<10} {'/'.join(req['types']):<26} "
                          f"{req['clause'][:105]}")

    if a.output:
        for r in recs:
            r.pop("_x", None)
        with open(a.output, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n\nwrote {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
