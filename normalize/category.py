"""
normalize/category.py - the title -> category table, in ONE place.

This is the single definition of CATEGORY_PATTERNS and categorize(). It was
lifted verbatim out of analyze_pull.py so the analysis layer and enrich.py read
the SAME mapping; two copies drifting apart is the failure mode this prevents.
The patterns are NOT edited here - the vocabulary is settled work, extended
2026-09-02 in a deliberate realignment pass, and this move is byte-identical.

The table LABELS, it does not GATE. A record's category has no bearing on
applicability. Assignment is ADDITIVE: categorize() returns every matching
category, so a grocery meat cutter legitimately carries both Food Services and
Retail. No precedence, no single winner.

This is OUR derived axis. It is never merged with source_category (the source's
own verbatim labels) and neither falls back to the other.
"""

import re

# HEURISTIC title -> category map, nine categories per the master doc §4.
CATEGORY_PATTERNS = {
    # Vocab extended 2026-09-02 from the audit of applicable-but-UNCLASSIFIED
    # titles (grocery-store dept format, Target inbound, healthcare-support admin,
    # the housekeep* regex fix). Category is additive and ungated - it labels, it
    # does not gate - so these move no verdict.
    "Administrative": r"\b(admin|administrative|clerk|clerical|receptionist|data entry|office assistant|front desk|scheduler|scheduling coord\w*|bookkeeper|human resources|\bhr\b|payroll|patient financial|revenue cycle|patient service[s]? (representative|coordinator)|registrar|registration|health information|\bhim\b|medical records)\b",
    "Customer Service": r"\b(customer service|call center|call centre|csr|customer support|contact center|dispatcher)\b",
    "Sales": r"\b(sales|account executive|canvasser|telesales|inside sales|outside sales|business development)\b",
    "Retail": r"\b(retail|cashier|store associate|sales associate|stocker|merchandiser|barista|shift lead|store manager|store mgr|asst store mgr|assistant store manager|dept leader|department leader|person in charge|\bpic\b|th person|rd person|nd person|team lead\w*|general merchandise|grocery|produce|meat|seafood|floral|apparel|garden ctr|dairy|starbucks|bakery|courtesy|bagger|checkout)\b",
    "Warehouse": r"\b(warehouse|forklift|picker|packer|material handler|order selector|loader|shipping|receiving|fulfillment|inbound|outbound|logistics|inventory|materials|supply chain|stocking|replenish)\b",
    "Construction": r"\b(construction|laborer|labourer|carpenter|roofer|framer|concrete|apprentice|helper|demolition)\b",
    "Security": r"\b(security|guard|patrol|loss prevention|surveillance|unarmed|armed officer)\b",
    "Facilities": r"\b(janitor|custodian|cleaner|housekeep\w*|facilities|maintenance|groundskeep|porter|environmental service|\bevs\b|engineer|journeyman)\b",
    # Ninth category. Patterns DERIVED from the captured corpus (Compass food-service
    # board + Providence dietary/nutrition titles), not guessed.
    # Grocery FOOD departments dual-tag Food Services AND Retail (a meat wrapper
    # works with food and is in-store) - additive, so both lanes. Pure retail
    # (cashier, courtesy, bagger) stays Retail-only; 'grocery'/center-store aisle
    # stocking stays Retail (not food-handling).
    "Food Services": r"\b(cook|baker|barista|bartender|chef|dishwasher|busser|server|waiter|waitress|catering|culinary|kitchen|cafeteria|concession|dietary|dining|nutrition|food service|foodservice|food worker|food prep|food transporter|banquet|deli|meat|seafood|produce|bakery|dairy|starbucks|order builder|general utility|food unit|\bfoh\b|\bfsw\b|food and beverage|meat cutter|meat wrapper)\b",
}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def categorize(title):
    t = _norm(title)
    hits = [c for c, pat in CATEGORY_PATTERNS.items() if re.search(pat, t)]
    return hits or ["UNCLASSIFIED"]
