"""
Load and validate config/sourcing_rules.json.

This is the ONLY place the rules file is read. Every consumer goes through
`load_rules()`; nothing hardcodes an exclusion, threshold, gate or carve-out.
`rules_hash()` fingerprints the ruleset so the store can tell when a candidate's
disposition was computed against a stale ruleset and needs re-evaluation.
"""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PATH = os.path.join(ROOT, "config", "sourcing_rules.json")


class RulesError(Exception):
    """The rules file is missing or structurally invalid."""


# Sections we require to exist so a consumer can trust the shape without
# re-checking. Values are the type each section must be.
_REQUIRED = {
    "exclusions": list,
    "deprioritized": list,
    "segments": dict,
    "footprint": dict,
    "size": dict,
    "thresholds": dict,
    "gates": dict,
    "carve_outs": list,
}


def load_rules(path=None):
    """Return the parsed, validated rules dict. Raises RulesError on any problem.

    Reads the file every call by design — the acceptance test flips a rule on
    disk and re-runs; caching here would defeat that. Callers that classify a
    whole batch should load once and pass the dict down.
    """
    p = path or RULES_PATH
    try:
        with open(p, "r", encoding="utf-8") as fh:
            rules = json.load(fh)
    except FileNotFoundError:
        raise RulesError(f"sourcing rules not found at {p}")
    except json.JSONDecodeError as e:
        raise RulesError(f"sourcing rules is not valid JSON: {e}")

    for key, typ in _REQUIRED.items():
        if key not in rules:
            raise RulesError(f"sourcing rules missing required section {key!r}")
        if not isinstance(rules[key], typ):
            raise RulesError(
                f"sourcing rules section {key!r} must be {typ.__name__}, "
                f"got {type(rules[key]).__name__}"
            )

    for sub in ("frontline", "non_frontline"):
        if sub not in rules["segments"] or not isinstance(rules["segments"][sub], list):
            raise RulesError(f"segments.{sub} must be a list")
    for sub in ("fail", "pass"):
        if sub not in rules["gates"] or not isinstance(rules["gates"][sub], list):
            raise RulesError(f"gates.{sub} must be a list")
    for sub in ("min_in_market_volume", "min_estimated_applicable"):
        if not isinstance(rules["thresholds"].get(sub), (int, float)):
            raise RulesError(f"thresholds.{sub} must be a number")

    return rules


def rules_hash(rules):
    """Stable fingerprint of the *meaningful* content of the ruleset.

    Underscore-prefixed keys (notes/comments) are stripped before hashing so a
    comment edit does not trigger a re-evaluation, but any real rule change does.
    """
    canon = json.dumps(_strip_notes(rules), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _strip_notes(obj):
    if isinstance(obj, dict):
        return {k: _strip_notes(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_notes(v) for v in obj]
    return obj


# --- typed accessors so consumers never re-walk the raw shape ---------------

def exclusions(rules):
    """List of {name|class, reason}. Permanent — never opens a browser."""
    return rules["exclusions"]


def deprioritized(rules):
    """List of {segment, status(hold|exclude), note}. Classified and held."""
    return rules["deprioritized"]


def frontline_segments(rules):
    return set(rules["segments"]["frontline"])


def non_frontline_segments(rules):
    return set(rules["segments"]["non_frontline"])


def footprint_tier_weight(rules):
    return rules["footprint"]["tier_weight"]


def size_band_effect(rules):
    return rules["size"]["band_effect"]


def thresholds(rules):
    return rules["thresholds"]


def gates(rules):
    return rules["gates"]


def carve_outs(rules):
    return [c["rule"] for c in rules["carve_outs"]]
