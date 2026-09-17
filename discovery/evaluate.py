"""
Stage 2 evaluation — the role-level requirement gate + the candidate disposition.

The gate clauses in config/sourcing_rules.json are natural language ("degree
requirement", "will train or paid training"). The READER (the browser operator in
Stage 2) decides which clause a sampled description hits and passes that hit in
here as `gate_hit`. This module does the deterministic part: apply the carve-outs
that override a title reflex, tally the sample, and — most importantly — enforce
the two invariants that must never be violated:

  * DENSITY NEVER REJECTS. A low sampled-applicable count is needs_review, never a
    reject. (Cintas read 0 applicable until per-tenant openers were forked, then 57.)
  * INDUSTRY LABEL NEVER REJECTS. A wrong segment guess is re-labelled, never a
    reject. (Cornerstone read construction and was manufacturing; Sysco read
    warehouse and was mostly sales and CDL.)

These are exposed as functions (`density_rejects`, `label_rejects`) that always
return False, so a test can assert the invariant directly and a future edit that
tries to make density reject has to delete an obviously-named guard.
"""
import re

from . import rules as R
from .record import (
    DISPOSITION_QUALIFIED,
    DISPOSITION_NEEDS_REVIEW,
)

PASS = "PASS"
FAIL = "FAIL"
NOT_STATED = "NOT_STATED"

# Carve-out predicates over a title. Deterministic slices of the natural-language
# carve_outs list; the operator still reads the body, but these settle the common
# title reflexes the same way every time.
_INTERNSHIP_RX = re.compile(r"\b(intern|internship|apprentice(ship)?|co-?op)\b", re.I)
_TRAINING_PROGRAM_RX = re.compile(r"\b(management|sales|leadership)\b.*\b(training|development)\s+program\b", re.I)
_CDL_RX = re.compile(r"\bCDL\b|commercial driver'?s? licen[sc]e", re.I)
_BADGING_RX = re.compile(r"\b(badg(e|ing)|background check|drug screen|e-verify)\b", re.I)


def density_rejects(*_a, **_k):
    """INVARIANT: density never rejects at Stage 2. Always False."""
    return False


def label_rejects(*_a, **_k):
    """INVARIANT: an industry label never rejects at Stage 2. Always False."""
    return False


def classify_role(title, gate_hit, rules):
    """Verdict for one sampled role.

    title     the posting title
    gate_hit  the rules clause the reader matched (a string from gates.fail /
              gates.pass), or None if the description stated nothing.

    Returns (verdict, explanation). Carve-outs are applied before the raw gate.
    """
    g = R.gates(rules)
    fails = set(g["fail"])
    passes = set(g["pass"])

    # Carve-outs first — they override a title/gate reflex.
    if _INTERNSHIP_RX.search(title or ""):
        return FAIL, "carve-out: internships and long-runway apprenticeships remain excluded"
    if _CDL_RX.search(title or "") or (gate_hit and _CDL_RX.search(gate_hit)):
        return PASS, "carve-out: CDL stays in via the quick-cert exception"
    if gate_hit and _BADGING_RX.search(gate_hit):
        # A badging/background requirement is the employer's screen, not a gate fail.
        gate_hit = None
    if _TRAINING_PROGRAM_RX.search(title or ""):
        # Do not fail on the management/sales title; defer to the requirement gate.
        if gate_hit in fails:
            pass  # a real stated requirement still fails
        elif gate_hit in passes:
            return PASS, "carve-out: training program deferred to gate, gate passed"
        else:
            return NOT_STATED, "carve-out: training program, no requirement stated"

    if gate_hit is None:
        return NOT_STATED, "no requirement stated (excluded from density, like NOT_STATED openers)"
    if gate_hit in fails:
        return FAIL, f"gate fail: {gate_hit}"
    if gate_hit in passes:
        return PASS, f"gate pass: {gate_hit}"
    return NOT_STATED, f"gate_hit {gate_hit!r} not in the rules' fail/pass clauses"


def summarize_sample(roles, rules):
    """Tally a sampled set into the record's sampled_applicable shape.

    roles: list of {"title": str, "gate_hit": str|None}
    returns {"n": passes, "m": scored, "rejects": [{"title","gate"}], "not_stated": k}
    """
    n = 0
    scored = 0
    not_stated = 0
    rejects = []
    for role in roles:
        verdict, why = classify_role(role.get("title", ""), role.get("gate_hit"), rules)
        if verdict == NOT_STATED:
            not_stated += 1
            continue
        scored += 1
        if verdict == PASS:
            n += 1
        else:
            rejects.append({"title": role.get("title", ""), "gate": role.get("gate_hit")})
    return {"n": n, "m": scored, "rejects": rejects, "not_stated": not_stated}


def _market_problems(market, scope, th):
    """Gate one market's captured scope. Returns a list of problems ([] = clears).

    Same invariants as the single-market gate: scope + row locations must be
    verified; a measured volume below the floor is a FIXABLE thin-market flag;
    density (estimated applicable) never rejects — it only flags needs_review.
    """
    probs = []
    if scope.get("scope_verified") is not True:
        probs.append("scope not verified")
    if scope.get("row_locations_verified") is not True:
        probs.append("row locations not verified (geo-drift risk)")
    vol = scope.get("in_market_volume")
    if vol is not None and scope.get("basis") == "measured" and vol < th["min_in_market_volume"]:
        probs.append(f"volume {vol} < min {th['min_in_market_volume']} (thin, fixable)")
    sa = scope.get("sampled_applicable") or {}
    if sa:
        n, m = sa.get("n", 0), sa.get("m", 0)
        est = sa.get("estimated_applicable")
        if est is None and m:
            est = round(vol * n / m) if vol else n
        if est is not None and est < th["min_estimated_applicable"]:
            probs.append(f"est applicable {est} < min {th['min_estimated_applicable']} (needs_review; density never rejects)")
    return probs


def stage2_disposition(cand, rules):
    """Turn captured Stage-2 facts into a disposition. Returns (disposition, rationale).

    The only two outcomes here are QUALIFIED and NEEDS_REVIEW. Stage 2 NEVER emits
    a permanent reject: density and label problems both fall to needs_review so a
    human can fork openers / re-label rather than losing the employer. The
    permanent verdicts (excluded, ruled_out) are Stage 1's job.

    Multi-market: if per-market scope was captured (`market_scope`), the candidate
    is QUALIFIED when AT LEAST ONE target market clears all gates — a thin WA does
    not sink a strong TX (WFS: WA 15, TX 68). Each market is its own scoped config.
    """
    th = R.thresholds(rules)

    ms = cand.market_scope or {}
    if ms:
        cleared, per_market = [], []
        for m, s in ms.items():
            probs = _market_problems(m, s, th)
            if probs:
                per_market.append(f"{m}: " + "; ".join(probs))
            else:
                cleared.append(f"{m}({s.get('in_market_volume')})")
        if cleared:
            note = "market(s) cleared: " + ", ".join(cleared)
            if per_market:
                note += " | held: " + " | ".join(per_market)
            return DISPOSITION_QUALIFIED, note
        return DISPOSITION_NEEDS_REVIEW, "no market cleared -> " + " | ".join(per_market)

    problems = []

    if cand.scope_verified is not True:
        problems.append("scope not verified")
    if cand.row_locations_verified is not True:
        problems.append("returned row locations not verified (geo-drift risk - U-Haul resolved the bare state to Washington DC)")

    if cand.in_market_volume is not None and cand.in_market_volume_basis == "measured":
        if cand.in_market_volume < th["min_in_market_volume"]:
            problems.append(
                f"in-market volume {cand.in_market_volume} < min {th['min_in_market_volume']} "
                f"(FIXABLE — revisit, do not permanently reject)"
            )

    sa = cand.sampled_applicable or {}
    if sa:
        n, m = sa.get("n", 0), sa.get("m", 0)
        est = sa.get("estimated_applicable")
        if est is None and m:
            # Extrapolate the sample's applicable RATIO across the measured
            # in-market volume — "applicable jobs in this market", not the raw
            # sample count. Falls back to the sample count if volume is unknown.
            if cand.in_market_volume:
                est = round(cand.in_market_volume * n / m)
            else:
                est = n
        if est is not None and est < th["min_estimated_applicable"]:
            # Density NEVER rejects: this is needs_review, never a reject.
            problems.append(
                f"estimated applicable {est} < min {th['min_estimated_applicable']} — "
                f"needs_review (density never rejects; may be uncalibrated openers, cf. Cintas 0->57)"
            )

    if problems:
        return DISPOSITION_NEEDS_REVIEW, "; ".join(problems)
    return DISPOSITION_QUALIFIED, (
        f"scope+rows verified, volume {cand.in_market_volume} ({cand.in_market_volume_basis}), "
        f"sample {sa.get('n','?')}/{sa.get('m','?')} applicable"
    )
