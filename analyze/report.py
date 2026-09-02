#!/usr/bin/env python3
"""
analyze/report.py - the consolidated applicable set across all tenants.

THE LAST STEP BEFORE THE CARD. Reads every out/*/*/normalized.jsonl, applies the
four gates in order, dedupes across employers (not within), and emits one
out/applicable.jsonl plus a report.

INPUT IS THE CONTRACT ONLY. No adapter imports. The shared extractor
(normalize/experience.py) is re-run against each record's description with that
tenant's forked opener vocabulary - this is the "combined pass re-runs everything
against current code" step, which is why per-employer numbers move from their
historical values. normalize/model.py supplies the field list; nothing here knows
a source's field names.

THE FOUR GATES, IN ORDER (first failing gate is the recorded reason):

  1. EXCLUSION - structured field + title only, NO description read.
     - degree: education_flag. A bachelor's/master's/doctorate excludes. An
       associate degree goes to REVIEW (not excluded, not applicable). High
       school / GED / none passes.
     - occupation: title. MANAGEMENT is non-overridable (a management title is
       excluded even if it also carries a protected word). The protect list keeps
       ASSISTANT and TRAINEE titles that are not themselves management.
  2. EXPERIENCE - experience_condition. REQUIRED excludes. PREFERRED, NONE_NEEDED
     and WAIVED pass.
  3. CREDENTIAL - a credential required TO APPLY must be obtainable within ~90
     days with no prerequisite; one failing credential disqualifies. AFTER_HIRE
     credentials are not barriers.
  4. UNKNOWN IS NOT OPEN - NOT_STATED never counts as applicable.

POLICY TERM LISTS are defined here as data and printed in the report so they can
be calibrated. The occupation soft-vs-hard split and the credential allowlist are
this script's operationalization of the stated policy - report, don't fix.

Run:  python -m analyze.report
"""

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from normalize import model             # noqa: E402  contract field list only
from normalize import experience as X   # noqa: E402  shared extractor (current code)

OUT_GLOB = os.path.join(ROOT, "out", "*", "*", "normalized.jsonl")
APPLICABLE_PATH = os.path.join(ROOT, "out", "applicable.jsonl")

# Historical applicable counts, produced at different times with different
# extractor code. Reported for comparison; the combined pass supersedes them.
HISTORICAL = {"providence": 42, "kroger": 303}

# ---- gate 1: exclusion policy (structured field + title only) ---------------
DEGREE_EXCLUDE_RX = re.compile(
    r"\b(bachelor|master|doctor|doctoral|ph\.?d|four[- ]year degree|"
    r"4[- ]year degree|college degree)\b", re.IGNORECASE)
DEGREE_REVIEW_RX = re.compile(r"\bassociate", re.IGNORECASE)

# MANAGEMENT is non-overridable. Deliberately does NOT include generic
# "lead"/"leader" (frontline "Team Leader" is not management here); the experience
# gate handles those.
MANAGEMENT_RX = re.compile(
    r"\b(manager|management|director|supervisor|superintendent|foreman|"
    r"principal|chief|president|vice president|\bvp\b|executive|general manager)\b",
    re.IGNORECASE)
# Protected occupations: kept unless the title is also management.
PROTECT_RX = re.compile(r"\b(assistant|trainee|apprentice)\b", re.IGNORECASE)

# ---- gate 3: credential obtainability ---------------------------------------
# Obtainable within ~90 days, no prerequisite -> passes.
CREDENTIAL_QUICK_RX = re.compile(
    r"(food handler|food safety|servsafe|guard card|security guard (license|card)|"
    r"\bbls\b|\bcpr\b|basic life support|first aid|\baed\b|forklift|"
    r"osha[- ]?10|\btabc\b|tips certification|driver'?s? licen[sc]e)", re.IGNORECASE)
# Anything that names a credential but is not on the quick list is treated as a
# prerequisite/long-lead barrier (RN/LPN/CNA licences, ARRT, CDL, pharmacist,
# therapist, CPA, ACLS/PALS held to apply, degree-based certs, ...).

# ---- gate 3b: prose prerequisite ------------------------------------------
# The acceptable-jobs rule has TWO conditions: obtainable within ~90 days AND no
# prerequisite. CREDENTIAL_QUICK_RX only reasons about NAMED credentials, so a
# prerequisite stated as prose - "satisfactory completion of a formal ultrasound
# technology training program" - is invisible to it. That is how a sonographer
# rendered as "No experience needed". A TO_APPLY clause naming a program/course/
# apprenticeship the applicant must already hold is a hard prerequisite: it fails
# the second condition regardless of timeframe. Deliberately not exhaustive; it
# fails in the safe direction (drops the record) and is scoped to TO_APPLY only,
# so an after-hire "complete our training program" path is untouched.
PREREQUISITE_RX = re.compile(
    r"completion of (?:an?\s+)?(?:[\w\-/]+\s+){0,6}(?:program|course)|"
    r"graduate of (?:an?\s+)?accredited|"
    r"accredited program|training program|degree program|"
    r"certificate program|apprenticeship program", re.IGNORECASE)


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def tenant_of(path):
    parts = path.replace("\\", "/").split("/")
    return parts[-2]                    # out/<platform>/<tenant>/normalized.jsonl


def load_records():
    """Every normalized record, with experience re-derived by the current
    extractor using the tenant's forked openers. Returns list of dicts."""
    recs = []
    for path in sorted(glob.glob(OUT_GLOB)):
        tenant = tenant_of(path)
        openers = X.load_openers(tenant)
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                xo = X.extract(r.get("description_html") or "",
                               r.get("description_text") or "",
                               r.get("qualifications_html") or "", openers)
                r["experience_condition"] = xo["experience_condition"]
                r["evidence_clauses"] = xo["evidence_clauses"]
                r["credentials"] = xo["credentials"]
                r["_tenant"] = tenant
                r["_cred_to_apply"] = xo["credentials_to_apply"]
                r["_to_apply"] = [rq["clause"] for rq in xo["requirements"]
                                  if rq["modality"] == X.TO_APPLY]
                recs.append(r)
    return recs


# ---------------------------------------------------------------------------
# gates - return (passed: bool, reason: str|None). Reason set only on failure.
# ---------------------------------------------------------------------------

def gate_exclusion(r):
    edu = r.get("education_flag") or ""
    if DEGREE_EXCLUDE_RX.search(edu):
        return False, "degree"
    title = r.get("title") or ""
    # The protect list PRECEDES the occupation rule, distinguished by POSITION: a
    # title is protected when a protect word is the HEAD NOUN of the role phrase -
    # the last word before any " - " / "," / "/" department-or-location suffix - not
    # a modifier. "Executive Assistant" and "Administrative Assistant - Case
    # Management" have head "assistant" -> protected. "Assistant Manager" and
    # "Assistant Nurse Manager" have head "manager" -> NOT protected, so management
    # stays non-overridable on genuine management roles.
    primary = re.split(r"\s[-–—]\s|[,/]", title)[0]
    toks = re.findall(r"[A-Za-z]+", primary)
    head = toks[-1] if toks else ""
    protected = bool(PROTECT_RX.search(head))
    if not protected and MANAGEMENT_RX.search(title):
        return False, "occupation-management"
    # associate degree -> review (handled by caller as a separate bucket)
    if DEGREE_REVIEW_RX.search(edu):
        return False, "review-associate"
    return True, None


def gate_experience(r):
    if r.get("experience_condition") == "REQUIRED":
        return False, "experience-required"
    return True, None


def gate_credential(r):
    # Evaluate PER CREDENTIAL, not per clause. A clause can bundle several
    # credentials ("Active BLS, ACLS, and PALS certifications are required"); split
    # on commas, slashes and "and"/"&" and disqualify if ANY *named* credential is
    # not quick-obtainable. A split part counts as naming a credential only if it
    # carries a credential cue (so filler like "certifications are required" alone
    # does not disqualify). "or" is deliberately NOT a split point - it is
    # either-acceptable, so a quick option in an "X or BLS" clause still passes.
    for clause in r.get("_cred_to_apply") or []:
        for part in re.split(r",|/|&|\band\b", clause):
            low = part.lower()
            names_credential = any(cue in low for cue in X.CREDENTIAL_CUES)
            if names_credential and not CREDENTIAL_QUICK_RX.search(part):
                return False, "credential"
    return True, None


def gate_prerequisite(r):
    # A TO_APPLY clause naming a program/course/apprenticeship the applicant must
    # already have completed is a hard prerequisite - fails the second condition
    # of acceptability (no prerequisite), independent of any named credential.
    for clause in r.get("_to_apply") or []:
        if PREREQUISITE_RX.search(clause):
            return False, "prerequisite"
    return True, None


def gate_unknown(r):
    if r.get("experience_condition") == "NOT_STATED":
        return False, "not-stated"
    return True, None


GATES = (gate_exclusion, gate_experience, gate_credential,
         gate_prerequisite, gate_unknown)


def verdict(r):
    for g in GATES:
        ok, reason = g(r)
        if not ok:
            return reason
    return "applicable"


# ---------------------------------------------------------------------------
# cross-employer dedupe
# ---------------------------------------------------------------------------

def cross_key(r):
    city = r.get("city") or r.get("location_raw") or ""
    return (_norm(r.get("title")), _norm(city), _norm(r.get("state")))


def dedupe_across_employers(applicable):
    """Collapse a job that appears under more than one EMPLOYER to a single
    record; keep within-employer records as-is. Returns (kept, collisions)."""
    groups = defaultdict(list)
    for r in applicable:
        groups[cross_key(r)].append(r)
    kept, collisions = [], []
    for ck, rs in groups.items():
        employers = {r.get("company_name") for r in rs}
        sources = {r.get("source_id") for r in rs}
        if len(employers) > 1 or len(sources) > 1:
            collisions.append((ck, rs))
            kept.append(rs[0])                 # dedupe across employers -> keep one
        else:
            kept.extend(rs)                    # within-employer -> keep all
    return kept, collisions


# ---------------------------------------------------------------------------
# pay band
# ---------------------------------------------------------------------------

def pay_band(r):
    if not r.get("salary_is_stated") or r.get("salary_min") is None:
        return "unstated"
    if r.get("pay_period") != "HOURLY":
        return f"non-hourly ({r.get('pay_period')})"
    v = r["salary_min"]
    for hi, lab in ((15, "< $15"), (18, "$15-17.99"), (21, "$18-20.99"),
                    (25, "$21-24.99"), (30, "$25-29.99")):
        if v < hi:
            return lab
    return "$30+"


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def main():
    recs = load_records()
    by_tenant = defaultdict(list)
    for r in recs:
        by_tenant[r["_tenant"]].append(r)

    verdicts = {id(r): verdict(r) for r in recs}
    applicable = [r for r in recs if verdicts[id(r)] == "applicable"]
    kept, collisions = dedupe_across_employers(applicable)

    with open(APPLICABLE_PATH, "w", encoding="utf-8") as fh:
        for r in kept:
            out = {k: v for k, v in r.items() if not k.startswith("_")}
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")

    L = []
    def p(s=""):
        L.append(s)

    p("=" * 90)
    p("CONSOLIDATED APPLICABLE SET - all tenants, combined pass against current extractor")
    p("=" * 90)
    p(f"\nread {len(recs)} normalized records from {len(by_tenant)} tenants: "
      f"{', '.join(f'{t} {len(rs)}' for t, rs in sorted(by_tenant.items()))}")

    # ---- headline ----
    p("\n\n### TOTAL APPLICABLE\n")
    p(f"  {len(kept)} applicable after all four gates and cross-employer dedupe")
    p(f"  ({len(applicable)} before dedupe; {len(applicable) - len(kept)} collapsed)")

    p("\n### PER EMPLOYER - combined (current code) vs historical\n")
    p(f"  {'tenant':<14}{'records':>9}{'applicable':>12}{'density':>9}{'historical':>12}")
    ded_by_tenant = Counter(r["_tenant"] for r in kept)
    for t, rs in sorted(by_tenant.items()):
        appl = ded_by_tenant.get(t, 0)
        hist = HISTORICAL.get(t)
        p(f"  {t:<14}{len(rs):>9}{appl:>12}{appl/len(rs)*100:>8.1f}%"
          f"{(str(hist) if hist is not None else '-'):>12}")
    p("\n  historical: counted at earlier times with earlier extractor code; the")
    p("  combined column is the real figure now. Providence and Kroger moved.")

    # ---- gate attribution ----
    p("\n\n### WHERE RECORDS FELL (first failing gate)\n")
    reasons = Counter(verdicts[id(r)] for r in recs)
    for k in ("applicable", "degree", "occupation-management", "review-associate",
              "experience-required", "credential", "prerequisite", "not-stated"):
        p(f"  {reasons.get(k, 0):>6}  {k}")

    # ---- fill matrix ----
    p("\n\n### FILL MATRIX - every contract field x every tenant (populated %)\n")
    p("  Decides whether the card renders from the contract or needs per-source")
    p("  special-casing. A column that is 0% on one tenant and 100% on another is")
    p("  exactly such a case.")
    p("  NOTE on derived rows: experience_condition is the combined-pass value (100%")
    p("  by construction, recomputed here). experience_condition, evidence_clauses and")
    p("  credentials are now PERSISTED to normalized.jsonl by normalize.enrich, so they")
    p("  read at their true fill on disk. category stays an empty [] - the shape exists")
    p("  before the title table lands. education_flag is adapter-populated. All other")
    p("  rows are adapter state.\n")
    tenants = sorted(by_tenant)
    hdr = f"  {'field':<24}" + "".join(f"{t[:10]:>11}" for t in tenants)
    p(hdr)
    p("  " + "-" * (len(hdr) - 2))
    for f in model.FIELDS:
        cells = []
        for t in tenants:
            rs = by_tenant[t]
            filled = sum(1 for r in rs if r.get(f) not in (None, "", [], {}, False)
                         or (f == "salary_is_stated" and r.get(f) is True))
            cells.append(f"{filled/len(rs)*100:>10.0f}%")
        p(f"  {f:<24}" + "".join(cells))

    # ---- breakdowns (over the applicable, deduped set) ----
    p("\n\n### APPLICABLE BREAKDOWN - by experience_condition\n")
    for k, n in Counter(r["experience_condition"] for r in kept).most_common():
        p(f"  {n:>6}  {k}")

    p("\n### APPLICABLE BREAKDOWN - by source_function\n")
    for k, n in Counter((r.get("source_function") or "(none)") for r in kept).most_common(30):
        p(f"  {n:>6}  {k}")

    p("\n### APPLICABLE BREAKDOWN - by pay band\n")
    for k, n in Counter(pay_band(r) for r in kept).most_common():
        p(f"  {n:>6}  {k}")

    # ---- collisions ----
    p("\n\n### CROSS-EMPLOYER DEDUPE COLLISIONS\n")
    if not collisions:
        p("  none. No applicable job appears under more than one employer.")
        p("  (Providence and Swedish share one board but are one tenant/company here,")
        p("   so their overlap is within-employer and is not deduped.)")
    else:
        p(f"  {len(collisions)} job(s) appear under more than one employer:")
        for ck, rs in collisions[:40]:
            emps = ", ".join(sorted({r.get('company_name') or r.get('source_id') for r in rs}))
            p(f"    {ck[0]} | {ck[1]}, {ck[2]}")
            p(f"       spans: {emps}")

    # ---- policy lists (for calibration) ----
    p("\n\n### GATE POLICY APPLIED (printed for calibration)\n")
    p(f"  degree-exclude : {DEGREE_EXCLUDE_RX.pattern}")
    p(f"  degree-review  : {DEGREE_REVIEW_RX.pattern}")
    p(f"  management     : {MANAGEMENT_RX.pattern}")
    p(f"  protect        : {PROTECT_RX.pattern}")
    p(f"  credential-ok  : {CREDENTIAL_QUICK_RX.pattern}")
    p("  NOTE: the occupation soft/hard split and the credential allowlist are this")
    p("  script's operationalization of the stated policy - calibrate, don't assume.")

    report = "\n".join(L)
    print(report)
    with open(os.path.join(ROOT, "out", "applicable_report.txt"), "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\n\nwrote {APPLICABLE_PATH}")
    print(f"wrote {os.path.join(ROOT, 'out', 'applicable_report.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
