"""
normalize/pay.py - description-text pay parser.

THE GAP THIS CLOSES. Adapters fill salary_min/max/pay_period/salary_is_stated
ONLY from a source's STRUCTURED pay fields. Many employers state pay only in the
description prose (Washington requires a wage range in postings from employers
with 15+ employees), so those records land with salary_is_stated=False and the
card shows nothing. This module reads the number the employer wrote in the text.

FIVE RULES, NON-NEGOTIABLE (they are the reason this file is conservative):

  1. ONLY what the employer states. Never infer, estimate, convert, or round. A
     period is read from an explicit cue ("per hour", "Hourly", "annually"); it is
     never guessed from the size of the number.
  2. STRUCTURED WINS. This parser is a fallback. The caller runs it ONLY when
     salary_is_stated is already False. It never overwrites a structured number.
  3. TRACEABILITY. Every value this produces carries its source sentence
     (pay_evidence) and is tagged pay_source="description". The caller tags
     pre-existing structured pay pay_source="structured".
  4. NON-WAGE AMOUNTS ARE IGNORED. Sign-on/referral bonuses, tuition, relocation,
     discounts, 401(k) — a dollar figure next to any of these is rejected. A match
     that is ambiguous (unknown period, two conflicting ranges, out of a sane
     band) fills NOTHING. Empty is the safe answer.
  5. HOURLY vs ANNUAL ARE KEPT DISTINCT. No conversion between them, ever.

DUAL RANGE (TJX). Some postings state a STARTING range and a separate FULL range.
We capture both as candidates but DO NOT pick which displays — that is a product
decision. decide() returns no fill and sets a review flag for a human.

PURE. This file imports only stdlib and knows no source names. Same input, same
output. Run `python -m normalize.pay` for the built-in template self-test.
"""

import re

# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

# A dollar amount: $21, $21.65, $1,250, $120,000.00. Group captured per use.
_AMT = r"\d[\d,]*(?:\.\d{1,2})?"

# Period cue that may trail a number. "hourly rate" in a FRAME also implies HOURLY
# (see resolve_period) — this list is only the trailing unit.
_UNIT = (r"per\s+hour|/\s*hour|/\s*hr\b|an\s+hour|a\s+hour|hourly|hour|"
         r"per\s+year|/\s*year|/\s*yr\b|a\s+year|per\s+annum|annually|annual|yearly|"
         r"per\s+week|weekly|per\s+month|monthly")

# Non-wage words: a frame IMMEDIATELY preceded by one of these is describing a
# bonus/perk, not a wage ("annual bonus ranges from $10k to $20k"). Rule 4. We
# check only the short, same-sentence run just before the frame (see
# _nonwage_bound) so a legit "...a sign-on bonus. The pay range is $X" is kept.
NONWAGE_RX = re.compile(
    r"sign[-\s]?on|signing\s+bonus|referral|\bbonus(?:es)?\b|tuition|reimburs|"
    r"scholarship|relocation|\bdiscount|\b401\(?k\)?\b|stipend|allowance|\baward",
    re.I)

# ---------------------------------------------------------------------------
# frames - a wage number is only read when it sits inside an explicit pay frame.
# Each frame is strong enough on its own that a stray "$5,000 sign-on bonus" (no
# frame, no unit) never matches. Order matters: more specific frames first.
# ---------------------------------------------------------------------------

# A label may be followed by ':' or '-' before the money ("Pay: $20", "Pay Rate:
# $21 / Hour", "Payrate-$17.70/hr"), and the low-end '$' is the anchor.
_LEAD = r"\s*[:\-]?\s*(?:USD\s*)?\$\s?"
# "<label> for this position/role is $X" — the Aramark/Allied prose shape, where a
# short fixed filler sits between the label and the number.
_FOR_THIS = r"(?:for\s+this\s+(?:position|role)\s+)?(?:of|is)"

_RANGE_FRAME = (
    r"hourly\s+rate\s+ranges?\s+from|"
    r"starting\s+pay\s+range\s+of|"
    r"(?:the\s+)?full\s+range\s+of\s+the\s+position\s+is|"
    r"pay\s+range[^.$\n]{0,30}?\bis|"
    r"salary\s+range[^.$\n]{0,30}?\bis|"
    r"pay\s+range\s+of|salary\s+range\s+of|compensation\s+range\s+of|"
    r"pay\s+range|salary\s+range|compensation\s+range|"
    # "<label> for this position/role is $X - $Y" (Allied manager annual band)
    r"(?:hourly\s+rate|pay\s+rate|base\s+pay|pay|salary|wage|compensation)\s+for\s+this\s+(?:position|role)\s+is|"
    # bare label: "Pay: $X - $Y", "Pay Rate: ...", "Salary: ..."
    r"pay\s+rate|base\s+pay|payrate|pay|salary|wage|compensation|"
    # "ranges from $X to $Y" and "...base salary for this role ranges between $X - $Y/Hour"
    # (Cintas). "between" takes a '-' or 'to' separator like "from"; RANGE_RX handles both.
    r"ranges?\s+from|ranges?\s+between")

# The high-end '$' is optional ("$27.75-28.75"); an explicit period + sane band
# keep a stray second number out. A unit may sit after EITHER end
# ("$25.42/hr-$35.96/hr" as well as "$25.42-$35.96 / hour").
RANGE_RX = re.compile(
    r"\b(?P<frame>" + _RANGE_FRAME + r")" + _LEAD + r"(?P<lo>" + _AMT + r")"
    r"\s*(?P<u1>" + _UNIT + r")?\s*(?:USD\b\s*)?"
    r"\s*(?:to|through|–|—|-|~)\s*"
    r"(?:USD\s*)?\$?\s?(?P<hi>" + _AMT + r")\s*(?:USD\b\s*)?"
    r"\s*(?P<u2>" + _UNIT + r")?",
    re.I)

# "Starting at $X/hr - Up to $Y/hr" (FedEx): an explicit low-to-high band stated
# with floor/ceiling words rather than "range". Both ends are given, so it is a
# true range — distinct from a lone "Starting at $X" floor (FLOOR_RX below).
STARTUP_RANGE_RX = re.compile(
    r"\b(?P<frame>starting\s+at|pay\s+starts?\s+at)\s*\$\s?(?P<lo>" + _AMT + r")\s*(?P<u1>" + _UNIT + r")?"
    r"\s*[-–—]?\s*up\s+to\s*\$?\s?(?P<hi>" + _AMT + r")\s*(?P<u2>" + _UNIT + r")?",
    re.I)

# Floor: "Starting at $13/hr" / "Pay starts at $22.10/hour" / "wages beginning at
# $19.40". A floor is min only (max=None); the card renders it "From $X" — never a
# flat point. A trailing unit is REQUIRED (rule 1: no period, no fill).
FLOOR_RX = re.compile(
    r"\b(?P<frame>(?:pay\s+)?start(?:s|ing)?\s+at|starting\s+pay\s+of|"
    r"beginning\s+at|wages?\s+beginning\s+at)" + _LEAD + r"(?P<amt>" + _AMT + r")"
    r"\s*(?P<unit>" + _UNIT + r")",
    re.I)

# Point rate — a SINGLE figure (min == max). Floor words live in FLOOR_RX, not here.
_SINGLE_FRAME = (
    r"paying|pay\s+rate\s+of|pay\s+rate\s+is|pay\s+rate|pays|pay\s+is|pay\s+of|"
    # "<label> for this position/role is $X" — includes 'salary' for Cintas single-value comp
    # ("base salary for this role is $69,000/Year"). Still needs an explicit period (frame/unit).
    r"(?:hourly\s+rate|pay\s+rate|base\s+pay|salary|rate|wage|pay|compensation)\s+for\s+this\s+(?:position|role)\s+is|"
    r"payrate|rate\s+of|rate\s+is|compensation\s+of|wage\s+of|wage\s+is|"
    r"base\s+pay|compensation|wage|pay")

# The period may come from the trailing unit ("Pay Rate: $21 / Hour") OR from the
# frame itself ("The Hourly rate for this position is $19.50"). The unit is
# therefore optional — but a figure with NEITHER (a bare "pay is $22.00") resolves
# to UNKNOWN and is rejected, so rule 1 still holds and a bonus "$5,000" (no frame,
# no period) never fills.
SINGLE_RX = re.compile(
    r"\b(?P<frame>" + _SINGLE_FRAME + r")" + _LEAD + r"(?P<amt>" + _AMT + r")"
    r"\s*(?:USD\b\s*)?\s*(?P<unit>" + _UNIT + r")?",
    re.I)

# Sane wage bands per period. A figure outside its band is rejected, not clamped:
# a "$5,000" read as hourly, or a "$25" read as annual, is a parse error, and the
# safe answer to a parse error is empty pay (rule 4). These are guardrails, NOT
# inference — the period is still only ever read from an explicit cue.
_BANDS = {
    "HOURLY":  (2.0, 250.0),
    "WEEKLY":  (50.0, 10_000.0),
    "MONTHLY": (500.0, 100_000.0),
    "ANNUAL":  (10_000.0, 2_000_000.0),
}


def _num(s):
    return float(s.replace(",", ""))


def resolve_period(*cues):
    """Period from an EXPLICIT cue only, read from the frame OR a trailing unit —
    whichever carries it. 'Hourly rate ranges from...' and 'pay range per hour
    is...' both state the period inside the frame; 'ranges from $X to $Y per hour'
    states it in the trailing unit. No cue anywhere -> UNKNOWN, and an
    UNKNOWN-period figure is never filled (rule 1)."""
    for src in cues:
        s = (src or "").lower()
        if not s:
            continue
        if "hour" in s or "/hr" in s or "hourly" in s:
            return "HOURLY"
        if "year" in s or "/yr" in s or "yr" in s or "annual" in s or "annum" in s or "yearly" in s:
            return "ANNUAL"
        if "week" in s:
            return "WEEKLY"
        if "month" in s:
            return "MONTHLY"
    return "UNKNOWN"


def _kind(frame):
    f = (frame or "").lower()
    if "starting pay range" in f:
        return "starting_range"
    if "full range of the position" in f:
        return "full_range"
    return "range"


def _sane(lo, hi, period):
    band = _BANDS.get(period)
    if not band:
        return False
    for v in (lo, hi):
        if v is None:
            continue
        if not (band[0] <= v <= band[1]):
            return False
    return True


def _nonwage_bound(text, frame_start):
    """True when a non-wage word sits in the short run immediately before the pay
    frame WITHOUT a sentence break between — i.e. the frame's own subject is the
    bonus/perk ('annual bonus ranges from $X'). A non-wage word in a PRIOR sentence
    ('...a sign-on bonus. The pay range is $X') is not bound and does not reject."""
    gap = text[max(0, frame_start - 16):frame_start]
    gap = gap.rsplit(".", 1)[-1].rsplit(";", 1)[-1]   # keep only the current clause
    return bool(NONWAGE_RX.search(gap))


def parse_pay(text, default_period=None):
    """Scan prose for stated wages. Returns:

        {
          "candidates": [ {kind, lo, hi, period, text}, ... ],   # accepted wage statements
          "rejected":   [ {amount(s), period, reason, text}, ... ],  # found-but-not-a-wage
        }

    candidates are the wage statements that passed every guard. rejected records
    every dollar figure that looked like it might be pay but was thrown out, with
    the reason — this is what makes rule 4 auditable. Neither list decides what to
    fill; see decide().

    default_period: a PER-TENANT override (never a global default). When a figure
    carries no explicit period AND the tenant config supplies one (e.g. Chipotle,
    owner-verified hourly), the figure is read at that period — still subject to the
    sane band, so a Chipotle annual "$55,000" read as HOURLY fails the band and
    stays empty rather than becoming $55,000/hr. Off (None) for every other tenant;
    without it, a period-less figure is rejected (rule 1)."""
    text = text or ""
    candidates = []
    rejected = []
    taken = []          # char spans already claimed by an earlier (range/floor) match

    def consider(lo, hi, period, frame_start, snippet, kind):
        if _nonwage_bound(text, frame_start):
            rejected.append({"lo": lo, "hi": hi, "period": period,
                             "reason": "non-wage context (bonus/tuition/etc.)",
                             "text": snippet})
            return
        if period == "UNKNOWN" and default_period:
            period = default_period                   # per-tenant override, band still applies
        if period == "UNKNOWN":
            rejected.append({"lo": lo, "hi": hi, "period": period,
                             "reason": "no explicit pay period", "text": snippet})
            return
        if not _sane(lo, hi, period):
            rejected.append({"lo": lo, "hi": hi, "period": period,
                             "reason": f"out of sane {period} band", "text": snippet})
            return
        candidates.append({"kind": kind, "lo": lo, "hi": hi,
                           "period": period, "text": snippet})

    def claim(m):
        taken.append((m.start(), m.end()))

    def overlaps(m):
        return any(s <= m.start() < e for s, e in taken)

    for m in STARTUP_RANGE_RX.finditer(text):
        claim(m)
        consider(_num(m.group("lo")), _num(m.group("hi")),
                 resolve_period(m.group("u1"), m.group("u2")),
                 m.start(), m.group(0).strip(), "range")

    for m in RANGE_RX.finditer(text):
        if overlaps(m):
            continue
        claim(m)
        consider(_num(m.group("lo")), _num(m.group("hi")),
                 resolve_period(m.group("frame"), m.group("u1"), m.group("u2")),
                 m.start(), m.group(0).strip(), _kind(m.group("frame")))

    for m in FLOOR_RX.finditer(text):
        if overlaps(m):
            continue
        claim(m)
        amt = _num(m.group("amt"))
        consider(amt, None, resolve_period(m.group("frame"), m.group("unit")),
                 m.start(), m.group(0).strip(), "floor")

    for m in SINGLE_RX.finditer(text):
        if overlaps(m):          # skip a single inside a range ("$21.30 to $21.80")
            continue
        amt = _num(m.group("amt"))
        consider(amt, amt, resolve_period(m.group("frame"), m.group("unit")),
                 m.start(), m.group(0).strip(), "single")

    return {"candidates": candidates, "rejected": rejected}


def decide(candidates):
    """Pick what to fill, or decline.

    Returns (fill, review) where fill is {salary_min, salary_max, pay_period,
    pay_evidence} or None, and review is a human-readable flag string or None.

      0 candidates          -> (None, None)                 nothing stated
      starting + full range -> fill the FULL range; keep the starting range in
                               pay_evidence (owner decision 2026-10-06, TJX)
      1 candidate           -> (fill, None)   (a floor fills salary_max=None)
      N identical           -> (fill, None)
      N conflicting         -> (None, 'ambiguous ...')      leave empty
    """
    if not candidates:
        return None, None

    kinds = {c["kind"] for c in candidates}
    if "starting_range" in kinds and "full_range" in kinds:
        start = next(c for c in candidates if c["kind"] == "starting_range")
        full = next(c for c in candidates if c["kind"] == "full_range")
        return ({"salary_min": full["lo"], "salary_max": full["hi"],
                 "pay_period": full["period"],
                 "pay_evidence": f"{full['text']}  [starting range: {start['text']}]"},
                None)

    uniq = []
    seen = set()
    for c in candidates:
        key = (c["lo"], c["hi"], c["period"])
        if key not in seen:
            seen.add(key)
            uniq.append(c)

    if len(uniq) == 1:
        c = uniq[0]
        return ({"salary_min": c["lo"], "salary_max": c["hi"],
                 "pay_period": c["period"], "pay_evidence": c["text"]}, None)

    return None, (f"{len(uniq)} differing pay statements "
                  f"({', '.join(c['period'] for c in uniq)}); ambiguous, left empty")


def fill_from_text(text, default_period=None):
    """Convenience: parse + decide in one call. Returns (fill|None, review|None,
    parse_result)."""
    pr = parse_pay(text, default_period=default_period)
    fill, review = decide(pr["candidates"])
    return fill, review, pr


# ---------------------------------------------------------------------------
# built-in self-test against the known live templates
# ---------------------------------------------------------------------------

# (name, text, want_fill, want_review, default_period)
_SAMPLES = [
    ("phenom/spencers",
     "Hourly rate ranges from $21.65 to $21.90 and is dependent upon qualifications and experience.",
     {"salary_min": 21.65, "salary_max": 21.90, "pay_period": "HOURLY"}, None, None),
    ("phenom/spirit",
     "Hourly rate ranges from $21.30 - $21.55 per hour",
     {"salary_min": 21.30, "salary_max": 21.55, "pay_period": "HOURLY"}, None, None),
    ("oracle_orc/sherwin",
     "This is a Part-Time role paying $22.00 Hourly.",
     {"salary_min": 22.00, "salary_max": 22.00, "pay_period": "HOURLY"}, None, None),
    ("target/reference",
     "The Pay Range / Rango salarial is $21.75 USD - $32.63 USD per hour.",
     {"salary_min": 21.75, "salary_max": 32.63, "pay_period": "HOURLY"}, None, None),
    ("tjx/dual->full",
     "This position has a starting pay range of USD $21.30 to $21.80 per hour. "
     "The Full Range of the position is $21.30 to $33.60 per hour.",
     {"salary_min": 21.30, "salary_max": 33.60, "pay_period": "HOURLY"}, None, None),
    ("reject/bonus",
     "We offer a $5,000 sign-on bonus and up to $3,000 in tuition reimbursement.",
     None, None, None),
    ("target/no-$-on-high",
     "The pay range per hour is $27.75-28.75. You may also earn additional compensation.",
     {"salary_min": 27.75, "salary_max": 28.75, "pay_period": "HOURLY"}, None, None),
    ("fedex/startup-range",
     "Starting at $23.21/hr- Up to $32.83/hr Additional Details: Full Time.",
     {"salary_min": 23.21, "salary_max": 32.83, "pay_period": "HOURLY"}, None, None),
    ("fedex/pay-label-range",
     "Pay Transparency: Pay: $20.75 - $24.37/hr Additional Details: ...",
     {"salary_min": 20.75, "salary_max": 24.37, "pay_period": "HOURLY"}, None, None),
    ("fedex/mid-unit-range",
     "Pay Transparency: Pay: $25.42/hr-$35.96/hr Additional Details: ...",
     {"salary_min": 25.42, "salary_max": 35.96, "pay_period": "HOURLY"}, None, None),
    ("allied/pay-rate-single",
     "Position Type: Full Time Pay Rate: $21.10 / Hour Job Schedule: Day Time",
     {"salary_min": 21.10, "salary_max": 21.10, "pay_period": "HOURLY"}, None, None),
    ("allied/pay-rate-usd",
     "advance notice. Pay Rate: USD $21.00/Hr. Client preferred years of work ...",
     {"salary_min": 21.00, "salary_max": 21.00, "pay_period": "HOURLY"}, None, None),
    ("aramark/hourly-for-this-position",
     "Compensation Data COMPENSATION: The Hourly rate for this position is $19.50.",
     {"salary_min": 19.50, "salary_max": 19.50, "pay_period": "HOURLY"}, None, None),
    ("floor-only/fills-from",
     "Pay starts at $22.10/hour. Click HERE to learn more.",
     {"salary_min": 22.10, "salary_max": None, "pay_period": "HOURLY"}, None, None),
    ("floor-only/jimmy",
     "Starting at $13 per hour, with room to grow.",
     {"salary_min": 13.0, "salary_max": None, "pay_period": "HOURLY"}, None, None),
    ("chipotle/default-hourly-apprentice",
     "A reasonable estimate of the current base pay range for this position is $25.65-$28.24.",
     {"salary_min": 25.65, "salary_max": 28.24, "pay_period": "HOURLY"}, None, "HOURLY"),
    ("chipotle/default-hourly-GM-rejected-by-band",
     "A reasonable estimate of the current base pay range for this position is $55,000.00-$77,500.00.",
     None, None, "HOURLY"),
    ("cintas/ranges-between-hourly",
     "Compensation A reasonable estimate of base salary for this role ranges between "
     "$19.25 - $24.08/Hour. The range takes into account factors ...",
     {"salary_min": 19.25, "salary_max": 24.08, "pay_period": "HOURLY"}, None, None),
    ("cintas/ranges-between-annual",
     "base salary for this role ranges between $82,960 - $106,140/Year and is eligible for "
     "an annual target bonus",
     {"salary_min": 82960.0, "salary_max": 106140.0, "pay_period": "ANNUAL"}, None, None),
    ("reject/bonus-range-bound",
     "An annual bonus ranges from $10,000 to $20,000 depending on performance.",
     None, None, None),
    ("keep/bonus-prior-sentence",
     "We offer a generous sign-on bonus. The pay range is $18.00 to $22.00 per hour.",
     {"salary_min": 18.00, "salary_max": 22.00, "pay_period": "HOURLY"}, None, None),
]


def _selftest():
    ok = True
    for name, text, want_fill, want_review, dp in _SAMPLES:
        fill, review, pr = fill_from_text(text, default_period=dp)
        got_fill = {k: fill[k] for k in ("salary_min", "salary_max", "pay_period")} if fill else None
        fill_ok = (got_fill == want_fill)
        review_ok = (want_review is None and review is None) or \
                    (want_review is not None and review is not None and want_review in review)
        status = "ok " if (fill_ok and review_ok) else "FAIL"
        if not (fill_ok and review_ok):
            ok = False
        print(f"[{status}] {name}")
        print(f"       fill={got_fill}")
        if review:
            print(f"       review={review}")
        if pr["rejected"]:
            for rj in pr["rejected"]:
                print(f"       rejected: {rj['reason']} :: {rj['text'][:60]}")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)
