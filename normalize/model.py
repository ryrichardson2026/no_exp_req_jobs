"""
normalize/model.py - the normalized job record.

THE ONLY CONTRACT. Every adapter writes into this shape; every layer above
reads only this shape. No source names, no source field names, no source SDKs.

Source independence, mechanical test: this file imports nothing from adapters/
and no adapter name appears in it. Grep for it.

ADDITIVE ONLY. Fields are added, never renamed or repurposed. A rename forces a
rebuild; an addition costs nothing. If a field turns out to be wrong, add the
right one beside it and leave the wrong one null.

Provenance discipline: fields prefixed `source_` hold the SOURCE's own values,
verbatim. Fields without that prefix hold OUR derived values. They are never
merged. Losing that distinction means never again being able to answer whether a
job landed in a category because the employer said so or because a rule inferred
it - and on at least one measured source the employer's own taxonomy is 100%
filled, which makes it the more trustworthy of the two.
"""

import hashlib
import re

SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Controlled vocabularies. A value outside these is a validation failure, not a
# silent pass - an unrecognised label is how a bad record looks normal.
# ---------------------------------------------------------------------------

EXPERIENCE_CONDITION = (
    "NONE_NEEDED",   # explicitly hires without experience
    "WAIVED",        # states experience, then removes it as a barrier
    "REQUIRED",
    "PREFERRED",     # wanted, not required
    "NOT_STATED",    # silent either way
)

PAY_PERIOD = ("HOURLY", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL", "UNKNOWN")

# How the record reached us. This governs how freshness may be USED, which is
# not the same on every source - see freshness_from_days.
SOURCE_CLASS = ("direct-employer", "aggregator", "public-feed")

# A posting is "new" by OUR first_seen, never by the employer's posted_at.
# posted_at says how long the employer has been hiring; first_seen says when
# this pipeline first saw it. Only the second is a fact about our inventory.
NEW_WINDOW_DAYS = 7

# `direct-contact` is proposed but NOT approved - it covers email, phone and
# in-person apply paths. Deliberately absent until that decision is made.
APPLY_CLASS = ("employer-direct", "ATS", "aggregator")

# Unknown is a real state, not a synonym for stale. On one measured source a
# third of records carried no posted date at all.
FRESHNESS_STATE = ("FRESH", "AGING", "STALE", "UNKNOWN")

FRESH_MAX_DAYS = 7
AGING_MAX_DAYS = 30


def new_record():
    """An empty record with every field present. Absent and null are the same
    thing here, and a field that is always present is a field that can be
    counted - which is what makes fill-rate reporting meaningful."""
    return {
        # identity
        "schema_version": SCHEMA_VERSION,
        "source_id": None,          # which adapter produced this
        "source_job_id": None,      # the source's own stable id (req number)
        "dedupe_hash": None,
        # Stable account-layer id (additive). Deterministic from source + the
        # source's requisition id, so a re-fetch keeps the SAME id and saved-jobs
        # / applied-disposition survive. Populated for records that reach the
        # applicable set; see internal_id().
        "internal_id": None,

        # employer
        "company_name": None,
        "employer_domain": None,

        # role
        "title": None,
        "description_html": None,
        "description_text": None,
        "qualifications": [],       # segmented block IF the source supplies one
        # Raw HTML of a source-supplied qualifications block, kept UNstripped so
        # the extractor can sectionize it by <li>/<p> boundaries. Distinct from
        # `qualifications` (stripped text, for display). Null where a source
        # carries no such block - e.g. Providence, where it is empty on 100% of
        # records and requirements live in description_html instead.
        "qualifications_html": None,

        # place
        "location_raw": None,
        "city": None,
        "state": None,
        "lat": None,
        "lng": None,
        "market": None,             # deferred - geography model not settled

        # terms
        "employment_type": None,
        "shift_raw": None,
        "salary_min": None,
        "salary_max": None,
        "salary_is_stated": False,  # False until an employer-published number parses
        "pay_period": "UNKNOWN",
        "fte": None,

        # time
        "posted_at": None,
        "first_seen": None,
        "last_seen": None,
        # Describes POSTING AGE only. On a direct-employer source it must never
        # drive removal or down-ranking - see freshness_from_days.
        "freshness_state": "UNKNOWN",
        # New to OUR inventory, by first_seen. This is the field ranking uses.
        "is_new": False,

        # apply
        "apply_url": None,
        "apply_class": None,
        "source_class": None,

        # source taxonomy - the SOURCE's own labels, verbatim, never merged
        # with our derived category[]
        "source_category": None,
        # How source_category was obtained. A field read verbatim from the payload
        # is the default (None). "employer-curated-query" marks a value recovered
        # by running the employer's own search+facet queries when the payload
        # carries NO taxonomy field - weaker evidence (free-text search: over- and
        # under-inclusive), and it must never be conflated with a field read.
        "source_category_method": None,
        "source_function": None,

        # derived - ours. Null until the extractor runs.
        "experience_condition": None,
        "evidence_clauses": [],
        "education_flag": None,
        "category": [],
        # Credentials named in the requirements, each with the modality it was
        # stated under and a timeframe when the clause gives one. modality is
        # TO_APPLY / PREFERRED / AFTER_HIRE - the distinction that lets an
        # after-hire credential render as a path, not a barrier. Additive: added
        # beside category, never merged into it.
        "credentials": [],

        # provenance
        "source_url": None,
        "retrieved_at": None,
        "terms_reference": None,
    }


FIELDS = tuple(new_record().keys())


# ---------------------------------------------------------------------------
# helpers - source-agnostic
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _norm(s):
    if not isinstance(s, str):
        return ""
    return _WS.sub(" ", _PUNCT.sub(" ", s.lower())).strip()


def dedupe_hash(company_name, title, location_raw):
    """company + title + location, the settled rule. Independently reproduced
    exactly by an unrelated source identifier on a 352-record sample, which is
    what confirms the rule is calibrated rather than merely plausible.

    This is the structured-key layer only. URL canonicalization and fuzzy
    fallback are separate layers and are not implemented here."""
    key = "|".join((_norm(company_name), _norm(title), _norm(location_raw)))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def internal_id(source_id, source_job_id):
    """Stable account-layer id, deterministic from source + the source's own
    requisition id.

    Keyed on (source_id, source_job_id) ONLY - never on dedupe_hash, title or
    location, which change when an employer edits a posting. So the same job
    re-fetched next week yields the identical id, and saved-jobs / applied-
    disposition (the settled account-layer features) do not break. A sequential
    counter would reissue ids every pull and is exactly what this avoids.

    Format: 'nxj_' + first 12 hex of sha256(source|reqid). Returns None if the
    source id is missing (a record with no stable source id cannot get a stable
    internal id)."""
    if not source_id or not source_job_id:
        return None
    key = f"{source_id}\x1f{source_job_id}"
    return "nxj_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def parse_money(value):
    """Return (number, is_stated).

    An employer may publish a number or explicitly withhold one - a literal
    'See Posting' was measured on ~6% of salary cells on a real board. Withheld
    is not zero and is not an error. It is False and None.

    Never coerce, never default to 0, never let a stray year in a string land in
    salary_min."""
    if value is None:
        return None, False
    if isinstance(value, (int, float)):
        return float(value), True
    s = str(value).strip().replace("$", "").replace(",", "")
    if not s:
        return None, False
    try:
        return float(s), True
    except ValueError:
        return None, False       # 'See Posting', 'DOE', 'Competitive', etc.


def compute_is_new(rec, now_days_fn=None):
    """New to OUR inventory. Uses first_seen, never posted_at.

    A role the employer posted 90 days ago and we ingested yesterday is new to
    every user who will ever see it. A role we have carried for a month is not,
    however recently the employer re-dated it."""
    fs = rec.get("first_seen")
    if not fs:
        return False
    days = now_days_fn(fs) if now_days_fn else None
    if days is None:
        return False
    return 0 <= days <= NEW_WINDOW_DAYS


def seen_key(rec):
    """Identity for first_seen tracking, across runs.

    Keyed on the SOURCE's own stable id, not on dedupe_hash. A requisition id
    survives an employer editing the title or moving the posting between
    facilities; dedupe_hash does not, and a changed hash would silently reset
    first_seen and make an old posting look new. Scoped by source_id because ids
    are only unique within a source."""
    return f"{rec.get('source_id')}:{rec.get('source_job_id')}"


def apply_seen_state(rec, state, now):
    """Set first_seen and last_seen from persisted state.

    first_seen is written ONCE, at first insert, and never touched again.
    last_seen advances on every run that finds the posting. Without this,
    expiry logic has nothing to measure against - both timestamps would read
    'the last time the pipeline ran', which is not a fact about the posting.

    Mutates rec and returns the updated state entry."""
    key = seen_key(rec)
    prior = state.get(key)
    rec["first_seen"] = (prior or {}).get("first_seen") or now
    rec["last_seen"] = now
    state[key] = {"first_seen": rec["first_seen"], "last_seen": now}
    return state[key]


def freshness_from_days(days):
    """POSTING AGE. Not a data-quality verdict.

    FRESHNESS RULES ARE PER SOURCE CLASS, NOT GLOBAL.

    On an AGGREGATOR, a stale posting is a defect: the aggregator has not
    noticed the job is gone, so its copy and the truth have drifted apart. The
    standing rule that a board showing roles filled two months ago is worse than
    useless was written against exactly that failure.

    On a DIRECT-EMPLOYER source the two cannot drift. The employer's board IS
    the truth. A posting live on it is live, and sixty days up means hard to
    fill, not filled - which for a no-experience audience may be a BETTER shot,
    not a worse one. Removing it invents an expiry the employer never declared.

    So on direct-employer sources:
      - age NEVER removes or down-ranks a posting
      - the only expiry signal is DISAPPEARANCE from the board, tracked by
        seen state, not by this function
      - age is a sort and a fact, and is uninterpretable until crossed against
        role type: hard-to-fill clinical roles sit open for months for reasons
        that say nothing about the record

    UNKNOWN when age cannot be established. Unknown is not fresh."""
    if days is None:
        return "UNKNOWN"
    if days < 0:
        return "UNKNOWN"          # future-dated; do not claim freshness
    if days <= FRESH_MAX_DAYS:
        return "FRESH"
    if days <= AGING_MAX_DAYS:
        return "AGING"
    return "STALE"


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

REQUIRED = ("source_id", "source_job_id", "title", "company_name", "dedupe_hash")


def validate(rec):
    """Return a list of problems. Empty list means the record is well formed.

    Well formed is not the same as correct. This catches shape errors, not
    wrong values."""
    problems = []

    unknown = set(rec) - set(FIELDS)
    if unknown:
        problems.append(f"unknown field(s): {sorted(unknown)}")

    for f in REQUIRED:
        if not rec.get(f):
            problems.append(f"missing required: {f}")

    def enum(field, allowed, nullable=True):
        v = rec.get(field)
        if v is None and nullable:
            return
        if v not in allowed:
            problems.append(f"{field}={v!r} not in {allowed}")

    enum("experience_condition", EXPERIENCE_CONDITION)
    enum("pay_period", PAY_PERIOD, nullable=False)
    enum("apply_class", APPLY_CLASS)
    enum("source_class", SOURCE_CLASS)
    enum("freshness_state", FRESHNESS_STATE, nullable=False)

    for f in ("salary_is_stated", "is_new"):
        if not isinstance(rec.get(f), bool):
            problems.append(f"{f} must be a bool")

    # A number without salary_is_stated=True is a derived figure masquerading as
    # a published one. That confusion produced a part-time warehouse role listed
    # at $207K-289K on another source.
    if (rec.get("salary_min") is not None or rec.get("salary_max") is not None) \
            and not rec.get("salary_is_stated"):
        problems.append("salary present but salary_is_stated is False")

    if rec.get("salary_is_stated") and rec.get("pay_period") == "UNKNOWN":
        problems.append("salary stated but pay_period UNKNOWN - a bare number "
                        "is not usable to an hourly audience")

    lo, hi = rec.get("salary_min"), rec.get("salary_max")
    if lo is not None and hi is not None and lo > hi:
        problems.append(f"salary_min {lo} > salary_max {hi}")

    fs, ls = rec.get("first_seen"), rec.get("last_seen")
    if not fs or not ls:
        problems.append("first_seen and last_seen must both be set at insert")
    elif fs > ls:
        problems.append(f"first_seen {fs} is after last_seen {ls}")

    for f in ("qualifications", "evidence_clauses", "category", "credentials"):
        if not isinstance(rec.get(f), list):
            problems.append(f"{f} must be a list")

    for f in ("source_url", "retrieved_at"):
        if not rec.get(f):
            problems.append(f"missing provenance: {f}")

    return problems


def fill_report(records):
    """Fill rate per field. The direct counterpart to a source's own field
    reliability measurement - what is actually populated, not what is defined."""
    n = len(records)
    out = []
    for f in FIELDS:
        filled = sum(
            1 for r in records
            if r.get(f) not in (None, "", [], {}, False) or
            (f == "salary_is_stated" and r.get(f) is True)
        )
        out.append((f, filled, (filled / n * 100) if n else 0.0))
    return out
