"""
The candidate record — the handoff artifact between discovery and /add-tenant.

These field names ARE the contract. If discovery emits a field /add-tenant does
not consume, or omits one it needs, the seam is wrong and the fix is to align the
record here, never to add a translation layer on either side.

Two field groups:
  * The /add-tenant inputs (CONSUMED): platform, tenant_identifiers, scope_params,
    rendering_mode, market — plus the common coordinates every tenants.json entry
    carries (company/label, careers_url, employer_domain, source_class, sector).
    tenant_identifiers and scope_params are deliberately platform-specific objects:
    a tenants.json entry's coordinate fields differ per platform (oracle_orc uses
    host/site_number; workday uses tenant/site; radancy uses org_id; phenom uses
    widgets_url; etc.), so the record carries them as an object bucket, not as flat
    columns. Their KEYS are the real tenants.json field names, so /add-tenant lifts
    them across with no renaming.
  * The approval-decision fields (NOT consumed by /add-tenant): footprint, size_band,
    segment, tier, role_mix, sampled_applicable, categories_fed, disposition,
    rationale, notes. These exist so a human can approve; they are dropped at the seam.
"""
from dataclasses import dataclass, field, asdict, fields as dc_fields


# Stage a candidate has reached. Drives resumability: a batch survives an
# interruption without re-running completed stages.
STAGE_NEW = "new"                # never classified
STAGE_CLASSIFIED = "classified"  # Stage 1 done (no network); has a tier or a Stage-1 disposition
STAGE_PROBED = "probed"          # Stage 2 browser pass done; facts captured
STAGE_HANDED_OFF = "handed_off"  # approved and passed to /add-tenant

# Disposition — the verdict. Permanent dispositions never merit a re-probe;
# fixable ones (volume, needs_review) are worth revisiting.
DISPOSITION_EXCLUDED = "excluded"            # permanent (exclusion rule)
DISPOSITION_DEPRIORITIZED = "deprioritized"  # classified and held (deprioritized rule)
DISPOSITION_RULED_OUT = "ruled_out"          # non-frontline segment
DISPOSITION_NEEDS_REVIEW = "needs_review"    # unknown/blank facts, or low estimate — human looks
DISPOSITION_CANDIDATE = "candidate"          # cleared Stage 1, tiered, awaiting browser pass
DISPOSITION_QUALIFIED = "qualified"          # cleared Stage 2, ready to hand to /add-tenant
DISPOSITION_PENDING = "pending"              # not yet dispositioned

# Which dispositions are PERMANENT (never revisit) vs FIXABLE (worth revisiting).
PERMANENT_DISPOSITIONS = {DISPOSITION_EXCLUDED, DISPOSITION_RULED_OUT}
FIXABLE_DISPOSITIONS = {DISPOSITION_NEEDS_REVIEW, DISPOSITION_DEPRIORITIZED}


@dataclass
class Candidate:
    # --- identity (Stage 1 inputs) ---
    company: str = ""
    domain: str = ""
    careers_url: str = ""
    segment: str = ""          # e.g. aviation_ground_services; "" = unknown -> drops a tier
    size_band: str = ""        # enterprise|large|mid|small|"" (unknown)
    footprint: str = ""        # national|regional|local|"" (unknown)
    tier: object = None        # 1|2|3|None — assigned by Stage 1

    # --- platform / read surface (Stage 2, CONSUMED by /add-tenant) ---
    platform: str = ""             # existing tenants.json key, or a NEW key name
    adapter_exists: object = None  # bool — True => Case A (config only)
    tenant_identifiers: dict = field(default_factory=dict)  # platform-specific coords
    rendering_mode: str = ""       # server | client
    front_end_vendor: str = ""     # when different from the ATS (e.g. Drupal over UltiPro)

    # --- scope / geo (Stage 2, CONSUMED where noted) ---
    market: str = ""               # CONSUMED — the PRIMARY market /add-tenant onboards first (e.g. "WA")
    target_markets: list = field(default_factory=list)  # decision-only — every market we intend to serve, e.g. ["WA","TX"]
    scope_params: dict = field(default_factory=dict)  # platform-specific, verified
    scope_verified: object = None  # bool — for the PRIMARY market
    in_market_volume: object = None  # int — PRIMARY market
    in_market_volume_basis: str = ""  # "measured" | "screening" — always labelled
    row_locations_verified: object = None  # bool — counts alone are not trusted
    # Per-market scope capture (decision-only). Keyed by market code ->
    # {in_market_volume, basis, scope_verified, row_locations_verified, sampled_applicable,
    #  scope_params}. The depth pass fills WA and TX here; `market`/`in_market_volume` above
    # mirror the primary. Each market becomes its OWN scoped /add-tenant config (second scoped
    # config), so `scope_params` here pins that one state.
    market_scope: dict = field(default_factory=dict)
    # Can this ATS express all target markets in ONE search? None=unknown (probe it),
    # True=one query can carry WA+TX, False=must run per-market. The onboard produces
    # separate per-market scoped configs REGARDLESS — this only records whether a single
    # combined query is also possible. Default to running both separately (always safe).
    combined_market_search: object = None

    # --- density / role mix (Stage 2, decision-only) ---
    role_mix: dict = field(default_factory=dict)  # {category: count} sampled
    sampled_applicable: dict = field(default_factory=dict)  # {"n":x,"m":y,"rejects":[{title,gate}]}
    categories_fed: list = field(default_factory=list)
    category_contribution: dict = field(default_factory=dict)

    # --- common tenants.json coordinates (CONSUMED) ---
    employer_domain: str = ""
    source_class: str = ""     # direct-employer, etc.
    sector: str = ""

    # --- verdict (decision-only) ---
    disposition: str = DISPOSITION_PENDING
    rationale: str = ""
    notes: str = ""

    # --- bookkeeping (not part of the /add-tenant contract) ---
    stage: str = STAGE_NEW
    rules_hash: str = ""       # ruleset the current disposition was computed against
    input_class: str = ""      # optional class tag from the input list (staffing_agency, aggregator, ...)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f.name for f in dc_fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def key(self):
        """Stable per-candidate key for the store. Domain is the identity."""
        return (self.domain or self.company).strip().lower()


# The subset of record fields that /add-tenant actually consumes. Acceptance #8
# checks the record carries exactly these; the rest is for the approval decision.
ADD_TENANT_INPUTS = (
    "company",
    "careers_url",
    "employer_domain",
    "source_class",
    "sector",
    "platform",
    "tenant_identifiers",
    "rendering_mode",
    "front_end_vendor",
    "market",
    "scope_params",
)

# Decision-only fields — present on the record, dropped at the seam.
DECISION_ONLY = (
    "footprint", "size_band", "segment", "tier",
    "role_mix", "sampled_applicable", "categories_fed", "category_contribution",
    "disposition", "rationale", "notes",
    "stage", "rules_hash", "input_class",
    "adapter_exists", "scope_verified", "in_market_volume",
    "in_market_volume_basis", "row_locations_verified", "domain",
    "target_markets", "market_scope", "combined_market_search",
)
