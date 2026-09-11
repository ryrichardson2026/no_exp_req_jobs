"""
normalize/category.py - the title -> category table, in ONE place.

This is the single definition of CATEGORY_PATTERNS and categorize(). It was
lifted verbatim out of analyze_pull.py so the analysis layer and enrich.py read
the SAME mapping; two copies drifting apart is the failure mode this prevents.
The patterns are edited here only in deliberate, movement-audited passes. The
vocabulary was extended 2026-09-02 (realignment). Phase A close-out 2026-09-06:
'clerk' removed from Administrative and 'helper' from Construction (shop-floor
titles, not office/trades work); the shared Retail vocabulary gained the phrases
'fuel center', 'service counter', 'home hardlines', 'front end', 'e-commerce' -
real retail concepts that 'clerk' had been masking, added engine-side (not tenant
config) because they are true at any grocery chain. Matched as PHRASES, never bare
'service'/'counter'/'front'. Audit: 56 title/employer pairs move, all correct;
retail phrases caused zero cross-employer movement.

Pass 2026-09-11 (uncategorized-applicable audit, all-tenant movement-checked): added
grocery overnight-stocking + LP + dietary phrases missed by the table -
Retail gained 'night clerk'/'overnight clerk'/'freight clerk'/'section leader'
(Kroger STORE/NIGHT CLERK et al.), Security gained 'asset(s) protection' (Kroger/
Target loss prevention), Food Services gained 'dietetic'/'diet clerk'/'steward'
(MultiCare/Morrison dietary, Levy/Compass kitchen steward). All matches verified
against every tenant's titles: zero wrong cross-employer moves. NOT addressed
here (they need NEW categories, a taxonomy decision, not a phrase edit): clinical
support (~44, a SECTOR not a function per the master doc), plant PRODUCTION
associates (~10, Cintas), and DELIVERY DRIVERS (~8).

Pass 2 2026-09-11 (owner-approved taxonomy EXPANSION 9 -> 13): the groups parked
above got their own FUNCTIONAL categories - Healthcare Support (patient-facing /
clinical-support roles; this SUPERSEDES the earlier "clinical is a sector, never a
category" stance - it is a function here, and a hospital cook/cleaner still sorts
to Food/Facilities), Production (Cintas plant floor), Driver (delivery/transport,
compound tokens so security patrol-drivers are NOT swept in), and Automotive
(U-Haul vehicle-repair shop). Sales gained 'wholesale', Food gained 'runner'. All
all-tenant movement-audited: Healthcare zero matches outside health-sector
employers, Driver zero Allied-security matches, Production Cintas-only. Applicable
uncategorized 66 -> 3 (an IT DBA, a branch coordinator, a badging tech - genuine
one-offs with no functional home). Still additive/ungated: no verdict moved.

The table LABELS, it does not GATE. A record's category has no bearing on
applicability. Assignment is ADDITIVE: categorize() returns every matching
category, so a grocery meat cutter legitimately carries both Food Services and
Retail. No precedence, no single winner.

This is OUR derived axis. It is never merged with source_category (the source's
own verbatim labels) and neither falls back to the other.
"""

import re

# HEURISTIC title -> category map. Thirteen categories: the master-doc §4 nine plus
# Healthcare Support / Production / Driver / Automotive (owner-approved 2026-09-11).
CATEGORY_PATTERNS = {
    # Vocab extended 2026-09-02 from the audit of applicable-but-UNCLASSIFIED
    # titles (grocery-store dept format, Target inbound, healthcare-support admin,
    # the housekeep* regex fix). Category is additive and ungated - it labels, it
    # does not gate - so these move no verdict.
    "Administrative": r"\b(admin|administrative|clerical|receptionist|data entry|office assistant|front desk|scheduler|scheduling coord\w*|bookkeeper|human resources|\bhr\b|payroll|patient financial|revenue cycle|patient service[s]? (representative|coordinator)|registrar|registration|health information|\bhim\b|medical records)\b",
    "Customer Service": r"\b(customer service|call center|call centre|csr|customer support|contact center|dispatcher)\b",
    "Sales": r"\b(sales|account executive|canvasser|telesales|inside sales|outside sales|business development|wholesale)\b",
    "Retail": r"\b(retail|cashier|store associate|sales associate|stocker|merchandiser|barista|shift lead|store manager|store mgr|asst store mgr|assistant store manager|dept leader|department leader|person in charge|\bpic\b|th person|rd person|nd person|team lead\w*|general merchandise|fuel center|service counter|home hardlines|front end|e-commerce|grocery|produce|meat|seafood|floral|apparel|garden ctr|dairy|starbucks|bakery|courtesy|bagger|checkout|night clerk|overnight clerk|freight clerk|section leader)\b",
    "Warehouse": r"\b(warehouse|forklift|picker|packer|material handler|order selector|loader|shipping|receiving|fulfillment|inbound|outbound|logistics|inventory|materials|supply chain|stocking|replenish)\b",
    "Construction": r"\b(construction|laborer|labourer|carpenter|roofer|framer|concrete|apprentice|demolition)\b",
    "Security": r"\b(security|guard|patrol|loss prevention|surveillance|unarmed|armed officer|assets? protection)\b",
    "Facilities": r"\b(janitor|custodian|cleaner|housekeep\w*|facilities|maintenance|groundskeep|porter|environmental service|\bevs\b|engineer|journeyman)\b",
    # Ninth category. Patterns DERIVED from the captured corpus (Compass food-service
    # board + Providence dietary/nutrition titles), not guessed.
    # Grocery FOOD departments dual-tag Food Services AND Retail (a meat wrapper
    # works with food and is in-store) - additive, so both lanes. Pure retail
    # (cashier, courtesy, bagger) stays Retail-only; 'grocery'/center-store aisle
    # stocking stays Retail (not food-handling).
    "Food Services": r"\b(cook|baker|barista|bartender|chef|dishwasher|busser|server|waiter|waitress|catering|culinary|kitchen|cafeteria|concession|dietary|dining|nutrition|food service|foodservice|food worker|food prep|food transporter|banquet|deli|meat|seafood|produce|bakery|dairy|starbucks|order builder|general utility|food unit|\bfoh\b|\bfsw\b|food and beverage|meat cutter|meat wrapper|dietetic|diet clerk|steward|runner)\b",
    # Added 2026-09-11 (uncategorized-applicable pass 2, all-tenant movement-audited).
    # These are FUNCTIONS the original nine did not cover; category stays additive and
    # ungated. See the header note for the audit.
    # Healthcare Support: patient-facing / clinical-support functions (aides, techs,
    # therapists, patient sitters, medical assistants). This is a FUNCTION, distinct
    # from the clinical SECTOR - a hospital cook is Food Services, a hospital cleaner is
    # Facilities; only genuinely care-adjacent roles land here. Prefix tokens carry \w*
    # (social work\w* -> social worker, endoscop\w* -> endoscopic) per the housekeep\w*
    # convention. Verified: zero matches outside health-sector employers.
    "Healthcare Support": r"\b(patient|nurse|nursing|therapist|therapy|rehabilitation|rehab aide|mental health|behavioral health|social work\w*|chaplain|perfusion\w*|counsel\w*|medical assistant|clinical|caregiver|care aide|case aide|phlebotom\w*|eeg|ekg|ecg|neurodiagnostic|endoscop\w*|ophthalmic|perioperative|emergency department|constant observer|pediatric|developmental specialist|surgical tech\w*|medical receptionist)\b",
    # Production: plant / light-manufacturing floor roles (Cintas uniform-rental plant).
    # 'production associate' anchors it so a kitchen 'Food Production Worker' stays Food.
    "Production": r"\b(production associate|production operator|assembler|machine operator)\b",
    # Driver: delivery / transport as the JOB, matched on compound driver-types so it
    # does NOT catch a 'Security Officer ... Patrol Driver' (that stays Security only).
    "Driver": r"\b(delivery driver|truck driver|cdl|courier|route driver|transfer driver|catering driver|food transporter|delivery associate)\b",
    # Automotive: vehicle-repair shop roles (U-Haul brake/tire/engine/vanbody specialists).
    "Automotive": r"\b(brake|tire|engine specialist|vanbody|automotive|diesel technician)\b",
}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def categorize(title):
    t = _norm(title)
    hits = [c for c, pat in CATEGORY_PATTERNS.items() if re.search(pat, t)]
    return hits or ["UNCLASSIFIED"]
