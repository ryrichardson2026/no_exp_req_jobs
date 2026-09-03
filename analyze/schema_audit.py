#!/usr/bin/env python3
"""
analyze/schema_audit.py - measure the applicable set against Google's REQUIRED
JobPosting schema. READ-ONLY: reads out/applicable.jsonl and the shared extractor;
modifies nothing, adds nothing to the contract.

Google's five required properties: title, description, hiringOrganization,
jobLocation, datePosted. Everything else is Recommended/Beta. See the directive.

Run:  python -m analyze.schema_audit
"""

import datetime
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from normalize import experience as X   # noqa: E402  shared extractor (section detection)

APPLICABLE = os.path.join(ROOT, "out", "applicable.jsonl")
OUT_DIR = os.path.join(HERE, "out")
OUT_MD = os.path.join(OUT_DIR, "schema_audit.md")

# employer_domain -> (config tenant key for load_openers, display name).
# All seven are US-domiciled employers queried on WA/US geography, so
# addressCountry is adapter-declared (source constant), NOT record-derived - see
# directive 3.3. Reported as such; counted as resolvable.
DOMAIN_MAP = {
    "providence.org": ("providence", "Providence"),
    "kroger.com": ("kroger", "Kroger (Fred Meyer / QFC)"),
    "multicare.org": ("multicare", "MultiCare"),
    "target.com": ("target", "Target"),
    "aus.com": ("allied_security", "Allied Universal"),
    "dollargeneral.com": ("dollar_general", "Dollar General"),
    "compass-usa.com": ("compass_group", "Compass Group"),
}
EMPLOYER_ORDER = ["Providence", "Kroger (Fred Meyer / QFC)", "MultiCare", "Target",
                  "Allied Universal", "Dollar General", "Compass Group"]

# employmentType canonical set (case-sensitive) - for Tier E "could populate".
EMP_TYPES = {"FULL_TIME", "PART_TIME", "CONTRACTOR", "TEMPORARY", "INTERN",
             "VOLUNTEER", "PER_DIEM", "OTHER"}


def parse_date(v):
    """A date or None. Handles ISO, non-padded Y-M-D, and datetime strings."""
    if not v:
        return None
    s = str(v).strip()
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def nonempty(v):
    return bool(v) and str(v).strip() != ""


def strip_tags(s):
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").split())


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def percentiles(vals):
    if not vals:
        return {}
    xs = sorted(vals)
    def p(q):
        if len(xs) == 1:
            return xs[0]
        i = q * (len(xs) - 1)
        lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
        return int(round(xs[lo] + (xs[hi] - xs[lo]) * (i - lo)))
    return {"min": xs[0], "p10": p(.10), "p25": p(.25), "median": p(.50),
            "p75": p(.75), "p90": p(.90), "max": xs[-1]}


def employer_of(r):
    dom = (r.get("employer_domain") or "").lower()
    if dom in DOMAIN_MAP:
        return DOMAIN_MAP[dom]
    return (None, r.get("company_name") or r.get("source_id") or "UNKNOWN")


# ---------------------------------------------------------------------------
# Tier R - the five required conditions
# ---------------------------------------------------------------------------

def tier_r_conditions(r):
    """dict condition -> bool. addressCountry is adapter-declared (always True)."""
    title = (r.get("title") or "").strip()
    desc_html = r.get("description_html") or ""
    desc_text = strip_tags(desc_html)
    c1 = nonempty(title)
    # description: non-empty and not identical to the title (Google forbids equal)
    c2 = nonempty(desc_html) and desc_text.strip().lower() != title.lower()
    c3 = nonempty(r.get("company_name"))
    # jobLocation: country resolvable (adapter-declared US) AND city or state present
    c4 = (nonempty(r.get("city")) or nonempty(r.get("state")))
    c5 = parse_date(r.get("posted_at")) is not None
    return {"title": c1, "description": c2, "hiringOrganization": c3,
            "jobLocation": c4, "datePosted": c5}


def main():
    if not os.path.exists(APPLICABLE):
        sys.exit(f"no applicable set at {APPLICABLE} - run analyze.report first")
    recs = [json.loads(l) for l in open(APPLICABLE, encoding="utf-8") if l.strip()]

    # section detection per record, using that tenant's forked openers
    openers_cache = {}
    for r in recs:
        key, disp = employer_of(r)
        r["_emp"] = disp
        r["_r"] = tier_r_conditions(r)
        r["_pass"] = all(r["_r"].values())
        sec = False
        train = False
        if key:
            if key not in openers_cache:
                openers_cache[key] = X.load_openers(key)
            xo = X.extract(r.get("description_html") or "", r.get("description_text") or "",
                           r.get("qualifications_html") or "", openers_cache[key])
            sec = xo["section_found"]
            train = any(X.TRAINING in rq["types"] for rq in xo["requirements"])
        r["_section"] = sec
        r["_training"] = train

    emps = [e for e in EMPLOYER_ORDER if any(r["_emp"] == e for r in recs)]
    extra = sorted({r["_emp"] for r in recs} - set(emps))
    emps += extra
    by = {e: [r for r in recs if r["_emp"] == e] for e in emps}
    CONDS = ["title", "description", "hiringOrganization", "jobLocation", "datePosted"]

    L = []
    def w(s=""):
        L.append(s)

    w("# Schema compliance audit - Tier R (Google-required JobPosting)")
    w(f"\nApplicable set: `out/applicable.jsonl`, {len(recs)} records (post cross-employer "
      f"dedupe), {len(emps)} employers.")
    w("addressCountry is adapter-declared US for all employers (source constant per "
      "directive 3.3), not record-derived - counted as resolvable.")

    # 1. headline
    w("\n## 1. Headline - Tier R pass rate\n")
    tot_pass = sum(1 for r in recs if r["_pass"])
    w(f"**Consolidated: {tot_pass}/{len(recs)} = {pct(tot_pass, len(recs))}**\n")
    w("| employer | records | Tier R pass | rate |")
    w("|---|---|---|---|")
    for e in emps:
        rs = by[e]; p = sum(1 for r in rs if r["_pass"])
        w(f"| {e} | {len(rs)} | {p} | {pct(p, len(rs))} |")

    # 2. failure breakdown per condition
    w("\n## 2. Failure breakdown - each required condition, count failing\n")
    hdr = "| employer | " + " | ".join(CONDS) + " |"
    w(hdr); w("|" + "---|" * (len(CONDS) + 1))
    for e in emps:
        rs = by[e]
        cells = []
        for c in CONDS:
            f = sum(1 for r in rs if not r["_r"][c])
            cells.append(f"{f} ({pct(f, len(rs))})")
        w(f"| {e} | " + " | ".join(cells) + " |")
    w("\nConsolidated per-condition PASS rate:")
    for c in CONDS:
        p = sum(1 for r in recs if r["_r"][c])
        w(f"- `{c}`: {pct(p, len(recs))} pass ({len(recs) - p} fail)")

    # 3. failing records, capped 25/employer
    w("\n## 3. Failing records (job id, failed conditions) - capped 25 per employer\n")
    any_fail = False
    for e in emps:
        fails = [r for r in by[e] if not r["_pass"]]
        if not fails:
            continue
        any_fail = True
        w(f"\n**{e}** - {len(fails)} failing:")
        for r in fails[:25]:
            jid = r.get("source_job_id") or r.get("internal_id")
            bad = [c for c in CONDS if not r["_r"][c]]
            w(f"- `{jid}` - failed: {', '.join(bad)}")
        if len(fails) > 25:
            w(f"- ... {len(fails) - 25} more")
    if not any_fail:
        w("None - every applicable record passes Tier R.")

    # 4. description completeness
    w("\n## 4. Description completeness (measured, not thresholded)\n")
    w("Length = character count of the stripped description text. No pass/fail on length.\n")
    w("| employer | min | p10 | p25 | median | p75 | p90 | max | has-section | zero-section |")
    w("|" + "---|" * 10)
    suspect = {}
    for e in emps:
        rs = by[e]
        lens = [len(strip_tags(r.get("description_html") or "")) for r in rs]
        d = percentiles(lens)
        hasS = sum(1 for r in rs if r["_section"])
        zero = len(rs) - hasS
        suspect[e] = [r for r in rs if not r["_section"]]
        w(f"| {e} | {d.get('min','')} | {d.get('p10','')} | {d.get('p25','')} | "
          f"{d.get('median','')} | {d.get('p75','')} | {d.get('p90','')} | {d.get('max','')} | "
          f"{hasS} | {zero} |")
    w("\n### Completeness-suspect (zero detected sections) - NOT failures, capped 25/employer\n")
    for e in emps:
        s = suspect[e]
        if not s:
            continue
        w(f"\n**{e}** - {len(s)} zero-section:")
        for r in s[:25]:
            jid = r.get("source_job_id") or r.get("internal_id")
            w(f"- `{jid}` - {len(strip_tags(r.get('description_html') or ''))} chars - "
              f"{(r.get('title') or '')[:50]}")
        if len(s) > 25:
            w(f"- ... {len(s) - 25} more")

    # 5. Tier E fill rates
    w("\n## 5. Tier E - recommended property fill rates (could populate)\n")
    def fill(rs, fn):
        return pct(sum(1 for r in rs if fn(r)), len(rs))
    checks = [
        ("employmentType", lambda r: nonempty(r.get("employment_type"))),
        ("baseSalary", lambda r: r.get("salary_is_stated") is True),
        ("identifier", lambda r: nonempty(r.get("source_job_id")) or nonempty(r.get("internal_id"))),
        ("experienceRequirements", lambda r: r.get("experience_condition") not in (None, "", "NOT_STATED")),
        ("educationRequirements(from credentials)", lambda r: bool(r.get("credentials"))),
        ("directApply(constant false)", lambda r: True),
        ("jobLocationType(remote)", lambda r: False),
    ]
    w("| employer | " + " | ".join(c[0] for c in checks) + " |")
    w("|" + "---|" * (len(checks) + 1))
    for e in emps:
        rs = by[e]
        w(f"| {e} | " + " | ".join(fill(rs, fn) for _, fn in checks) + " |")

    # 6. Tier P counts
    w("\n## 6. Tier P - display-only surface (no schema home), counts\n")
    w("| employer | shift detected | training language | speed language |")
    w("|" + "---|" * 4)
    for e in emps:
        rs = by[e]
        shift = sum(1 for r in rs if nonempty(r.get("shift_raw")))
        train = sum(1 for r in rs if r["_training"])
        w(f"| {e} | {shift} | {train} | N/A |")
    w("\n- `shift detected` = `shift_raw` non-empty.")
    w("- `training language` = extractor flagged a TRAINING-type requirement clause "
      "(existing cue logic, read-only).")
    w("- `speed language` = **N/A**: no contract field and no existing detector; not "
      "built this pass (would be a new feature). Size unknown - see guesses.")

    # 7. content-policy proxies
    w("\n## 7. Content-policy proxy counts\n")
    no_apply = sum(1 for r in recs if not nonempty(r.get("apply_url")))
    desc_eq = sum(1 for r in recs if not r["_r"]["description"] and nonempty(r.get("description_html")))
    w(f"- No apply URL (Google removes these): **{no_apply}** / {len(recs)}")
    w(f"- description == title: **{desc_eq}** / {len(recs)}")
    w("- Login-required apply flow: **unknown** - the contract does not record whether "
      "the apply destination requires login. Not guessed.")

    # 8. experience lever distribution
    w("\n## 8. Experience lever distribution (PREFERRED called out)\n")
    levers = ["NONE_NEEDED", "WAIVED", "REQUIRED", "PREFERRED", "NOT_STATED"]
    w("| employer | " + " | ".join(levers) + " | PREFERRED |")
    w("|" + "---|" * (len(levers) + 2))
    for e in emps:
        rs = by[e]
        c = Counter(r.get("experience_condition") for r in rs)
        w(f"| {e} | " + " | ".join(str(c.get(l, 0)) for l in levers) +
          f" | **{c.get('PREFERRED', 0)}** |")
    allc = Counter(r.get("experience_condition") for r in recs)
    w(f"\nConsolidated PREFERRED: **{allc.get('PREFERRED', 0)}** "
      f"(sizes the verbatim-emission work).")

    # 9. guesses
    w("\n## 9. Anything I had to guess / decide\n")
    w("- **Seven employers, not four.** The directive named four; the applicable set now "
      "spans seven (Allied Universal, Dollar General, Compass Group added since). I audited "
      "all seven - that is the applicable set. Filterable to four on request.")
    w("- **addressCountry** treated as adapter-declared US for all seven per directive 3.3 "
      "(source constant, not record-derived). Counted as resolvable. Permanent `country` "
      "contract field remains the recorded follow-up.")
    w("- **`speed language`** has no contract field and no existing detector; reported N/A, "
      "not built (constraint: build nothing else).")
    w("- **`educationRequirements`** fill uses `credentials` non-empty as the proxy per §2; "
      "`education_flag` is the other possible source (populated only on Kroger). Flagged, "
      "not resolved - the emitter will decide the mapping.")
    w("- **Login-required apply** is unknown to the contract; reported as unknown, not guessed.")
    w("- Applicable set read is the **deduped** `out/applicable.jsonl` (post cross-employer "
      "dedupe), i.e. the canonical shipping set.")

    report = "\n".join(L)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(report)
    print(f"\n\nwrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
