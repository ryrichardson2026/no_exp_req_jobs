"""
Per-candidate persistence. One JSON file per candidate, keyed by domain.

The store is what makes discovery a durable pipeline rather than a one-off pass:
  * RESUMABLE — a batch of 50 survives an interruption; completed stages are not
    re-run because each candidate's `stage` is persisted.
  * IDEMPOTENT — re-running a completed candidate returns its disposition; the
    orchestration checks `stage` before re-fetching (unless forced).
  * RE-EVALUABLE ON RULE CHANGE — `reevaluate_all` recomputes every disposition
    from the CACHED facts against the current rules, WITHOUT re-fetching. The
    fetched facts and the rule-derived verdict are separate concerns: classify()
    and stage2_disposition() are pure functions of (facts, rules), so re-running
    them touches only disposition/tier/rationale/rules_hash — never a network.

State dir: out/discovery/candidates by default (out/ is the gitignored working
tree), override with $DISCOVERY_STATE_DIR.
"""
import json
import os
import re

from . import rules as R
from . import classify as C
from . import evaluate as E
from .record import (
    Candidate,
    STAGE_PROBED,
    STAGE_HANDED_OFF,
    DISPOSITION_CANDIDATE,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DIR = os.path.join(ROOT, "out", "discovery", "candidates")


def state_dir():
    return os.environ.get("DISCOVERY_STATE_DIR", _DEFAULT_DIR)


def _slug(key):
    return re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_") or "unknown"


def _path(key):
    return os.path.join(state_dir(), _slug(key) + ".json")


def save(cand):
    os.makedirs(state_dir(), exist_ok=True)
    p = _path(cand.key())
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cand.to_dict(), fh, indent=2, ensure_ascii=False)
    os.replace(tmp, p)  # atomic — an interrupted write never corrupts state
    return p


def load(key):
    p = _path(key)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as fh:
        return Candidate.from_dict(json.load(fh))


def load_all():
    d = state_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            with open(os.path.join(d, fn), "r", encoding="utf-8") as fh:
                out.append(Candidate.from_dict(json.load(fh)))
    return out


def exists(key):
    return os.path.exists(_path(key))


def needs_reeval(cand, rules):
    """True if the candidate's disposition was computed against an older ruleset."""
    return cand.rules_hash != R.rules_hash(rules)


def _redispose(cand, rules):
    """Recompute the verdict from cached facts. Pure — never fetches.

    Stage is a fetch fact and is preserved; only the rule-derived verdict changes.
    A probed candidate that a rule now excludes becomes excluded but keeps its
    captured facts (so a later rule reversal restores it without re-fetching).
    """
    original_stage = cand.stage
    C.classify(cand, rules)  # sets Stage-1 disposition/tier/rationale + rules_hash
    if original_stage in (STAGE_PROBED, STAGE_HANDED_OFF) and cand.disposition == DISPOSITION_CANDIDATE:
        # Stage-1 still says "browser-worthy" and we already have Stage-2 facts:
        # let Stage 2 have the final word.
        disp, why = E.stage2_disposition(cand, rules)
        cand.disposition = disp
        cand.rationale = why
    cand.stage = original_stage
    return cand


def reevaluate_all(rules, only_stale=True):
    """Re-dispose every stored candidate against the current rules, no re-fetch.

    Returns a list of change dicts for the candidates whose disposition moved:
    [{key, company, old, new, rationale}]. When only_stale is True, candidates
    already stamped with the current rules_hash are skipped.
    """
    changes = []
    for cand in load_all():
        if only_stale and not needs_reeval(cand, rules):
            continue
        old = cand.disposition
        _redispose(cand, rules)
        save(cand)
        if cand.disposition != old:
            changes.append({
                "key": cand.key(), "company": cand.company,
                "old": old, "new": cand.disposition, "rationale": cand.rationale,
            })
    return changes


def apply_probe(key, patch, rules):
    """Merge Stage-2 browser findings onto a stored candidate, then re-dispose.

    `patch` is a partial candidate dict (platform, tenant_identifiers, rendering_mode,
    market, scope_params, scope_verified, in_market_volume, row_locations_verified,
    sampled_applicable, ...). The candidate must already exist from Stage 1. Marks
    it STAGE_PROBED and lets Stage 2 (evaluate.stage2_disposition) decide qualified
    vs needs_review. Returns the updated candidate, or None if unknown key.
    """
    cand = load(key)
    if cand is None:
        return None
    known = set(Candidate().to_dict().keys())
    for k, v in patch.items():
        if k in known and k not in ("disposition", "rationale", "tier", "stage", "rules_hash"):
            setattr(cand, k, v)
    cand.stage = STAGE_PROBED
    # Re-run Stage 1 first (a probe may have corrected segment/footprint/label),
    # then let Stage 2 have the final word when Stage 1 still says browser-worthy.
    C.classify(cand, rules)
    if cand.disposition == DISPOSITION_CANDIDATE:
        disp, why = E.stage2_disposition(cand, rules)
        cand.disposition = disp
        cand.rationale = why
    cand.stage = STAGE_PROBED
    save(cand)
    return cand


def upsert_classified(cand, rules, force=False):
    """Persist a candidate after Stage 1.

    Idempotent: if the candidate already exists and is not stale, its stored
    disposition is returned untouched (no re-classify) unless force=True. A brand
    new candidate is classified and saved.
    """
    existing = load(cand.key())
    if existing is not None and not force:
        if not needs_reeval(existing, rules):
            return existing
        # stale -> re-dispose the STORED record (keeps any Stage-2 facts), not the
        # thin incoming one.
        _redispose(existing, rules)
        save(existing)
        return existing
    C.classify(cand, rules)
    save(cand)
    return cand
