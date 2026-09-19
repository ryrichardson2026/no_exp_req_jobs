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

The table LABELS, it does not GATE. A record's category has no bearing on
applicability. Assignment is ADDITIVE: categorize() returns every matching
category, so a grocery meat cutter legitimately carries both Food Services and
Retail. No precedence, no single winner.

This is OUR derived axis. It is never merged with source_category (the source's
own verbatim labels) and neither falls back to the other.
"""

import re

# HEURISTIC title -> category map. Ten TITLE-MATCHED categories: the master-doc §4 nine plus
# Transportation/Automotive (owner-approved 2026-09-11). Production folds into Warehouse
# for now; Healthcare stays a SECTOR (aides applicable-but-uncategorized), both by owner
# decision - an earlier 9->13 expansion was reverted, see the git log.
# NOTE: the board has an 11th category, Grocery, that is NOT title-matched - it is assigned by
# TENANT in normalize/enrich.py (config/tenant_category.json). It intentionally has no pattern here.
CATEGORY_PATTERNS = {
    # Vocab extended 2026-09-02 from the audit of applicable-but-UNCLASSIFIED
    # titles (grocery-store dept format, Target inbound, healthcare-support admin,
    # the housekeep* regex fix). Category is additive and ungated - it labels, it
    # does not gate - so these move no verdict.
    "Administrative": r"\b(admin|administrative|clerical|receptionist|data entry|office assistant|front desk|scheduler|scheduling coord\w*|bookkeeper|human resources|\bhr\b|payroll|patient financial|revenue cycle|patient service[s]? (representative|coordinator)|registrar|registration|health information|\bhim\b|medical records)\b",
    # Aviation ground roles are routed by JOB FUNCTION into existing buckets (owner
    # 2026-09-17: "the job type not the industry or vertical"). Aviation is a SECTOR,
    # not a category - no 11th bucket. Passenger/wheelchair assistance = customer-facing.
    "Customer Service": r"\b(customer service|call center|call centre|csr|customer support|contact center|dispatcher|passenger service\w*|passenger assist\w*|wheelchair\w*|gate agent|dispatch agent|guest service|concierge)\b",
    "Sales": r"\b(sales|account executive|canvasser|telesales|inside sales|outside sales|business development)\b",
    # 'merch\w* assoc\w*' catches Merchandise/Merchandising Associate incl. the TJX typos
    # (Merchadise Assoc, Merchandise Associte); backroom/stockroom are the store back-of-house
    # associate titles (HomeGoods/Marshalls/TJ Maxx/Sierra) that carried no category before.
    "Retail": r"\b(retail|cashier|store associate|sales associate|stocker|merchandiser|merch\w* assoc\w*|backroom|stockroom|barista|shift lead|store manager|store mgr|asst store mgr|assistant store manager|dept leader|department leader|person in charge|\bpic\b|th person|rd person|nd person|team lead\w*|general merchandise|fuel center|service counter|home hardlines|front end|e-commerce|grocery|produce|meat|seafood|floral|apparel|garden ctr|dairy|starbucks|bakery|courtesy|bagger|checkout|night clerk|overnight clerk|freight clerk|section leader|wholesale|branch coordinator|dressing room|seasonal associate)\b",
    # 'production associate'/operator/assembler fold into Warehouse (owner 2026-09-11):
    # Cintas plant-floor roles sit here UNTIL production earns its own category by volume.
    # Anchored to 'production associate' so a kitchen 'Food Production Worker' stays Food.
    "Warehouse": r"\b(warehouse|forklift|picker|packer|package handler|material handler|order selector|loader|shipping|receiving|fulfillment|inbound|outbound|logistics|inventory|materials|supply chain|stocking|replenish|production associate|production operator|assembler|machine operator|ramp agent|ramp service agent|baggage|bag handler|cargo agent|cargo handler|air cargo|equipment room)\b",
    # 'apprentice' removed 2026-09-18: bare token mis-tagged non-trade apprentices as Construction
    # (Providence "Medical Assistant Apprentice" -> Construction). Real construction apprentices
    # still match via the trade tokens below; a bare "Apprentice" is not identifiably construction.
    # Movement-audited: 0 live records relied on the token for their category.
    "Construction": r"\b(construction|laborer|labourer|carpenter|roofer|framer|concrete|demolition)\b",
    "Security": r"\b(security|guard|patrol|loss prevention|surveillance|unarmed|armed officer|assets? protection)\b",
    # Pass 2026-09-18 (uncategorized-applicable audit, all-tenant movement-checked, 55 moves,
    # zero wrong cross-employer): custodial (not just custodian), groundskeep\w* (the bare
    # 'groundskeep' lost 'Groundskeeper' to the trailing word boundary), landscap\w*, laundry,
    # 'linen tech\w*' (NOT bare 'linen' — that mis-tagged Cintas 'Garment/Linen' PRODUCTION as
    # facilities: product noun, not laundry work), sanitation, recycl\w*, aircraft appearance
    # (WFS cabin cleaning). All Aramark/ABM/WFS frontline facilities titles the table missed.
    "Facilities": r"\b(janitor\w*|custodian|custodial|cleaner|cleaning|floor tech\w*|floor care|housekeep\w*|facilities|maintenance|groundskeep\w*|landscap\w*|porter|laundry|linen tech\w*|sanitation|recycl\w*|environmental services?|\bevs\b|engineer|journeyman|cabin service\w*|cabin agent|aircraft appearance)\b",
    # Ninth category. Patterns DERIVED from the captured corpus (Compass food-service
    # board + Providence dietary/nutrition titles), not guessed.
    # Grocery FOOD departments dual-tag Food Services AND Retail (a meat wrapper
    # works with food and is in-store) - additive, so both lanes. Pure retail
    # (cashier, courtesy, bagger) stays Retail-only; 'grocery'/center-store aisle
    # stocking stays Retail (not food-handling).
    "Food Services": r"\b(cook|baker|barista|bartender|chef|dishwasher|busser|server|waiter|waitress|catering|culinary|kitchen|cafeteria|concession|dietary|dining|nutrition|food service|foodservice|food worker|food prep|food transporter|banquet|deli|meat|seafood|produce|bakery|dairy|starbucks|order builder|general utility|food unit|\bfoh\b|\bfsw\b|food and beverage|meat cutter|meat wrapper|dietetic|diet clerk|steward|runner|restaurant team member|crew member|line cook|prep cook|broista|hostess|bar.?back|beverage (station|cart)|commissary|pantry)\b",
    # Tenth category (owner-approved 2026-09-11): Transportation/Automotive = delivery/
    # transport drivers + vehicle-repair shop roles, ONE category. Compound driver tokens
    # so a 'Security Officer ... Patrol Driver' is NOT swept in (stays Security only) -
    # all-tenant audited, zero Allied matches. Additive: a retail-automotive title (e.g.
    # a tire SALES associate) also hits Retail/Sales and carries both, by design.
    # Bare 'transporter' (owner 2026-09-11) catches Patient/Medical/Food Transporter; 'truck
    # sales' stays Sales (no bare 'truck'/'sales' token here). Healthcare-support roles were NOT
    # given a category (owner: clinical stays a sector, aides applicable-but-uncategorized, 2026-09-02).
    # Aircraft fueler/GSE/deicer = equipment & vehicle work -> here, not Warehouse (owner
    # 2026-09-17). 'gse <role>' requires a following role word so bare 'GSE' can't over-match.
    # 'driver i+\b' (2026-09-18) catches Aramark 'Driver I/II/III' transport grades WITHOUT
    # reintroducing bare 'driver' (which would sweep 'Patrol Driver' back into Transportation):
    # the i+\b tail requires the literal grade suffix, so 'Driver Instructor' etc. never match.
    "Transportation/Automotive": r"\b(delivery driver|truck driver|cdl|courier|route driver|transfer driver|catering driver|transporter|delivery associate|driver i+\b|brake|tire|engine specialist|vanbody|automotive|diesel technician|aircraft fueler|fueler|into.?plane|gse (mechanic|technician|operator|agent)|ground support equipment|de.?icer|deicing|valet|parking)\b",
}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def categorize(title):
    t = _norm(title)
    hits = [c for c, pat in CATEGORY_PATTERNS.items() if re.search(pat, t)]
    return hits or ["UNCLASSIFIED"]
