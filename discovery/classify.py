"""
Stage 1 — classify. NO NETWORK CALLS. Whole list, cheap.

Disposition order (first match wins), all driven by config/sourcing_rules.json:

  1. exclusions      -> excluded (PERMANENT). Match a company name or a class
                        (the input_class tag OR the segment) against the rules.
  2. deprioritized   -> deprioritized (status=hold) or excluded (status=exclude),
                        matched on segment.
  3. segment axis    -> ruled_out (non-frontline) | proceed (frontline) |
                        needs_review (unknown segment — never estimated).
  4. tier            -> footprint sets the base (heaviest weight); size demotes;
                        a blank/unknown footprint or size drops a tier.
                        Result: disposition=candidate at tier 1|2|3.

Thresholds and the requirement gate are Stage-2 concerns (they need a measured
volume and sampled descriptions); Stage 1 never invents them.

Everything here is a pure function of (candidate, rules). Re-running it against a
changed ruleset re-disposes with no re-fetch — that is the whole point.
"""
from . import rules as R
from .record import (
    Candidate,
    STAGE_CLASSIFIED,
    DISPOSITION_EXCLUDED,
    DISPOSITION_DEPRIORITIZED,
    DISPOSITION_RULED_OUT,
    DISPOSITION_NEEDS_REVIEW,
    DISPOSITION_CANDIDATE,
)

WORST_TIER = 3


def _name_match(company, excl_name):
    c = (company or "").strip().lower()
    n = (excl_name or "").strip().lower()
    if not c or not n:
        return False
    return n == c or n in c.split() or c.startswith(n + " ") or n in c


def _class_match(cand, excl_class):
    """A class exclusion matches the candidate's input_class tag OR its segment."""
    ec = (excl_class or "").strip().lower()
    if not ec:
        return False
    return ec in ((cand.input_class or "").strip().lower(),
                  (cand.segment or "").strip().lower())


def _check_exclusions(cand, rules):
    for ex in R.exclusions(rules):
        if "name" in ex and _name_match(cand.company, ex["name"]):
            return f"excluded by name rule: {ex['name']} - {ex.get('reason','')}"
        if "class" in ex and _class_match(cand, ex["class"]):
            return f"excluded by class rule: {ex['class']} - {ex.get('reason','')}"
    return None


def _check_deprioritized(cand, rules):
    seg = (cand.segment or "").strip().lower()
    for dp in R.deprioritized(rules):
        if (dp.get("segment", "").strip().lower()) == seg and seg:
            return dp  # {segment, status, note}
    return None


def _compute_tier(cand, rules):
    """Base tier from footprint (heaviest weight); size demotes; blanks drop a tier.

    Returns (tier:int in 1..WORST_TIER, notes:list[str]).
    """
    weights = R.footprint_tier_weight(rules)     # {national:1, regional:2, local:3}
    size_effect = R.size_band_effect(rules)      # {enterprise:0,...,small:1}
    notes = []

    fp = (cand.footprint or "").strip().lower()
    if fp in weights:
        tier = weights[fp]
    else:
        # Unknown/blank footprint: cannot credit a national build, drop a tier
        # below the best available footprint.
        tier = min(weights.values()) + 1
        notes.append("footprint blank -> dropped a tier (never estimated)")

    sb = (cand.size_band or "").strip().lower()
    if sb in size_effect:
        demote = size_effect[sb]
        if demote:
            notes.append(f"size_band {sb!r} demotes +{demote}")
        tier += demote
    else:
        tier += 1
        notes.append("size_band blank -> dropped a tier (never estimated)")

    tier = max(1, min(WORST_TIER, tier))
    return tier, notes


def classify(cand, rules):
    """Classify one candidate in place and return it. Pure; no network."""
    cand.rules_hash = R.rules_hash(rules)
    cand.stage = STAGE_CLASSIFIED

    # 1 — permanent exclusions
    reason = _check_exclusions(cand, rules)
    if reason:
        cand.disposition = DISPOSITION_EXCLUDED
        cand.rationale = reason
        cand.tier = None
        return cand

    # 2 — deprioritized (held or excluded) by segment
    dp = _check_deprioritized(cand, rules)
    if dp is not None:
        if dp.get("status") == "exclude":
            cand.disposition = DISPOSITION_EXCLUDED
            cand.rationale = f"deprioritized/exclude: {dp['segment']} — {dp.get('note','')}"
            cand.tier = None
        else:
            cand.disposition = DISPOSITION_DEPRIORITIZED
            cand.rationale = f"deprioritized/hold: {dp['segment']} — {dp.get('note','')}"
            cand.tier = None
        return cand

    # 3 — segment axis
    seg = (cand.segment or "").strip().lower()
    if not seg:
        cand.disposition = DISPOSITION_NEEDS_REVIEW
        cand.rationale = "segment unknown — cannot classify without estimating; human to label"
        cand.tier = None
        return cand
    if seg in R.non_frontline_segments(rules):
        cand.disposition = DISPOSITION_RULED_OUT
        cand.rationale = f"non-frontline segment {seg!r}: cannot supply no-experience frontline roles"
        cand.tier = None
        return cand
    if seg not in R.frontline_segments(rules):
        cand.disposition = DISPOSITION_NEEDS_REVIEW
        cand.rationale = (
            f"segment {seg!r} is neither frontline nor non-frontline in the rules — "
            f"add it to config/sourcing_rules.json segments, then re-run"
        )
        cand.tier = None
        return cand

    # 4 — frontline: tier it
    tier, notes = _compute_tier(cand, rules)
    cand.tier = tier
    cand.disposition = DISPOSITION_CANDIDATE
    bits = [f"frontline segment {seg!r}", f"footprint={cand.footprint or 'blank'}",
            f"size={cand.size_band or 'blank'}", f"-> tier {tier}"]
    if notes:
        bits.append("(" + "; ".join(notes) + ")")
    cand.rationale = "; ".join(bits)
    return cand


def classify_batch(cands, rules):
    """Classify a list; return it. Callers load rules once and pass it in."""
    for c in cands:
        classify(c, rules)
    return cands


def priority_order(cands):
    """Candidates that cleared Stage 1, best tier first, then size, then company.

    Only DISPOSITION_CANDIDATE rows are browser-worthy; everything else is held
    out of the browser pass (acceptance: no candidate reaches a browser without
    an approved tier).
    """
    size_rank = {"enterprise": 0, "large": 1, "mid": 2, "small": 3, "": 4}
    browsered = [c for c in cands if c.disposition == DISPOSITION_CANDIDATE]
    return sorted(
        browsered,
        key=lambda c: (c.tier or WORST_TIER + 1,
                       size_rank.get((c.size_band or "").lower(), 4),
                       c.company.lower()),
    )
